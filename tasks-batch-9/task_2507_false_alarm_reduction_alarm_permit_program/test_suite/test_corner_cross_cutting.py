"""Cross-cutting behaviour: revision guards, threshold flips, cascades, and variant divergence."""
from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID, get_success_data, validate_error,
    validate_error_is_one_of, validate_paginated, validate_success,
)

from test_helpers import api_errors as E
from test_helpers import assertions as A
from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import fixtures as X
from test_helpers import test_users as U

# The clock is parked one hour past the present-day convention so that every
# determination in a scenario lands on the same instant and anything derived
# from the clock (an auto-proposed order's effective_from, for example) is
# stable across the whole scenario.
CLOCK_DETERMINE = "2026-09-20T01:00:00Z"

# Six chargeable occurrences, all strictly after the first permit's
# new-installation grace through instant of 2026-08-31.
OCCURRENCES = [
    "2026-09-15T03:00:00Z",
    "2026-09-16T04:00:00Z",
    "2026-09-17T04:00:00Z",
    "2026-09-18T04:00:00Z",
    "2026-09-19T04:00:00Z",
    "2026-09-19T05:00:00Z",
]


def _commercial_premises(api, *, system_count=1, contact_count=2, schedule_overrides=None):
    """A COMMERCIAL premises with permitted systems and the clock at CLOCK_DETERMINE."""
    return X.setup_program_baseline(
        api,
        clock=CLOCK_DETERMINE,
        site_overrides={"occupancy_class": "COMMERCIAL"},
        schedule_overrides=schedule_overrides,
        contact_count=contact_count,
        system_count=system_count,
    )


def _at_second(instant):
    """An API instant reduced to whole-second UTC granularity for comparison."""
    text = str(instant)
    if "." in text:
        text = text.split(".")[0] + "Z"
    return text


def _counted_incidents(api, bundle, count):
    """Report and rule chargeable `count` alarms, one per permitted system."""
    return [
        X.create_counted_incident(api, bundle, bundle.system_ids[index], OCCURRENCES[index])
        for index in range(count)
    ]


def test_stale_alarm_site_version_blocks_a_second_suspension_order(api):
    """A suspension order carrying a premises revision that an accepted order already moved is refused.

    PRD §2.8 states: "Opening a suspension order against a premises requires
    `expected_alarm_site_version` carrying the client's last observed `version`
    of the target `AlarmSite`. If any other writer has advanced that site's
    version since the client read it, the create is rejected with
    `ERR_STALE_ALARM_SITE_VERSION` (HTTP 412)." It also states: "The client
    reads the parent, notes its `version`, and sends that value back with the
    write; if the parent's current `version` no longer equals the submitted
    value, the write is refused with HTTP 412 and the parent is left
    untouched." PRD §3.7 states of an accepted order: "Its
    `suspension_sequence` is the premises' `lifted_suspension_count` plus 1,
    and the premises' `version` rises by 1."

    Two drafters read the same premises revision. The first order is accepted
    and lifts the premises revision by one; the second still carries the
    revision both drafters read, so it is refused at HTTP 412, the premises
    revision does not move again, and no second order is created.

    Six chargeable occurrences are needed before an order may be opened at all:
    PRD §3.7 requires that "the premises' chargeable count under its governing
    counting window must be at or above `suspension_threshold_count`, else
    `ERR_SUSPENSION_BASIS_NO_LONGER_MET`", and §2.10 fixes that threshold's
    default at 6. Crossing it also auto-proposes an order covering the logical
    clock plus 10 days through 30 days after that — 2026-09-30 through
    2026-10-30 — so the hand-drafted intervals start on 2026-10-31, clear of it
    under the closed-interval geometry of §3.7.

    Design: Corner/cross_cutting_complexity_layers/occ_stale_alarm_site_version_blocks_a_second_suspension_order
    """
    bundle = _commercial_premises(api, system_count=6)
    incidents = _counted_incidents(api, bundle, 6)

    stale_version = X.site_version(api, bundle.site_id)
    orders_before = len(X.orders_of_site(api, bundle.site_id))

    first = api.create_suspension_order(
        F.suspension_order_payload(
            bundle.site_id,
            incidents[5].incident_id,
            "2026-10-31T00:00:00Z",
            "2026-11-30T00:00:00Z",
            stale_version,
        ),
        U.PROGRAM_ADMIN,
    )
    validate_success(first, 201)
    A.assert_status(get_success_data(first), "PROPOSED")
    after_first = X.get_site(api, bundle.site_id)
    assert after_first["version"] == stale_version + 1, (
        "an accepted suspension order must lift the premises revision by one, "
        f"was {stale_version}, now {after_first['version']}"
    )

    second = api.create_suspension_order(
        F.suspension_order_payload(
            bundle.site_id,
            incidents[1].incident_id,
            "2026-12-05T00:00:00Z",
            "2027-01-05T00:00:00Z",
            stale_version,
        ),
        U.PROGRAM_ADMIN,
    )
    validate_error(second, E.ERR_STALE_ALARM_SITE_VERSION, expected_status=412)

    A.assert_version_unchanged(after_first, X.get_site(api, bundle.site_id))
    assert len(X.orders_of_site(api, bundle.site_id)) == orders_before + 1, (
        "the refused draft must not have created a second order"
    )


def test_stale_alarm_site_version_blocks_a_second_payment_record(api):
    """A replayed payment carrying the premises revision the first payment already moved is refused.

    PRD §2.8 states: "Posting a payment against a premises account requires
    `expected_alarm_site_version` carrying the client's last observed `version`
    of the paying `AlarmSite`, and a mismatch is rejected with
    `ERR_STALE_ALARM_SITE_VERSION` (HTTP 412)." PRD §2.4 states: "Any
    operation that recomputes a derived counter on a parent — a premises
    roll-up, a docket seat count, a company counter — is a mutation of that
    parent and therefore refreshes its `updated_at` and bumps its `version`."

    The first tender is accepted, allocates against the premises' invoices and
    lifts the premises revision by one. The replay still carries the
    pre-payment revision, so it is refused at HTTP 412, the premises revision
    stands where the accepted tender left it, and exactly one payment row
    exists for the premises.

    Design: Corner/cross_cutting_complexity_layers/occ_stale_alarm_site_version_blocks_a_second_payment_record
    """
    bundle = _commercial_premises(api, system_count=3)
    _counted_incidents(api, bundle, 3)

    stale_version = X.site_version(api, bundle.site_id)

    first = api.create_payment_record(
        F.payment_record_payload(bundle.site_id, 5000, CLOCK_DETERMINE, stale_version),
        U.BILLING_CLERK,
    )
    validate_success(first, 201)
    first_payment = get_success_data(first)
    A.assert_status(first_payment, "APPLIED")
    A.assert_cash_conservation(first_payment)
    after_first = X.get_site(api, bundle.site_id)
    assert after_first["version"] == stale_version + 1, (
        "an accepted payment must lift the premises revision by one, "
        f"was {stale_version}, now {after_first['version']}"
    )

    replay = api.create_payment_record(
        F.payment_record_payload(bundle.site_id, 5000, CLOCK_DETERMINE, stale_version),
        U.BILLING_CLERK,
    )
    validate_error(replay, E.ERR_STALE_ALARM_SITE_VERSION, expected_status=412)

    A.assert_version_unchanged(after_first, X.get_site(api, bundle.site_id))
    rows = A.assert_total_count(
        api.list_payment_records(U.BILLING_CLERK, {"alarm_site_id": bundle.site_id}), 1
    )
    assert rows[0]["id"] == first_payment["id"], "only the first tender may have been recorded"


def test_stale_penalty_invoice_version_blocks_a_second_adjustment(api):
    """A second reduction carrying the pre-adjustment invoice revision is refused at HTTP 412.

    PRD §2.8 states: "Posting an adjustment against an invoice requires
    `expected_penalty_invoice_version` carrying the client's last observed
    `version` of that `PenaltyInvoice`, and a mismatch is rejected with
    `ERR_STALE_PENALTY_INVOICE_VERSION` (HTTP 412)." PRD §3.8 states: "The
    adjustment raises `adjusted_cents` and recomputes `outstanding_cents`" and
    "The invoice's `version` and the premises' `version` each rise by 1, and
    the premises' `outstanding_balance_cents` and `renewal_block_active` are
    recomputed."

    The third chargeable alarm at a COMMERCIAL premises is priced from the
    10000-cent tier times the 1.50 occupancy multiplier, so 15000 cents, and
    its invoice adds the 5% administrative fee of 750 for an assessed 15750. A
    first 1000-cent reduction is accepted, leaving 14750 outstanding and
    lifting the invoice revision by one; the replay against the stale revision
    is refused, so the reduction total stays at 1000.

    Design: Corner/cross_cutting_complexity_layers/occ_stale_penalty_invoice_version_blocks_a_second_adjustment
    """
    bundle = _commercial_premises(api, system_count=3)
    incidents = _counted_incidents(api, bundle, 3)

    invoice = X.invoice_for_incident(api, incidents[2].incident_id)
    A.assert_invoice_totals(
        invoice, subtotal_cents=15000, admin_fee_cents=750, assessed_cents=15750
    )
    invoice_id = invoice["id"]
    stale_version = invoice["version"]

    payload = {
        "adjustment_kind": "REDUCE",
        "amount_cents": 1000,
        "reason": "Documented monitoring-company error on the first verification call.",
        "expected_penalty_invoice_version": stale_version,
    }

    first = api.adjust_invoice(invoice_id, dict(payload), U.PROGRAM_ADMIN)
    validate_success(first, 200)
    after_first = X.get_invoice(api, invoice_id)
    assert after_first["version"] == stale_version + 1, (
        "an accepted adjustment must lift the invoice revision by one, "
        f"was {stale_version}, now {after_first['version']}"
    )
    A.assert_invoice_totals(after_first, adjusted_cents=1000, outstanding_cents=14750)

    replay = api.adjust_invoice(invoice_id, dict(payload), U.PROGRAM_ADMIN)
    validate_error(replay, E.ERR_STALE_PENALTY_INVOICE_VERSION, expected_status=412)

    final = X.get_invoice(api, invoice_id)
    A.assert_version_unchanged(after_first, final)
    A.assert_invoice_totals(final, adjusted_cents=1000, outstanding_cents=14750)
    A.assert_outstanding_identity(final)


def test_stale_alarm_system_version_blocks_a_second_reconfiguration(api):
    """A reconfiguration touching a different field than the accepted one is still refused as stale.

    PRD §2.8 states: "Reconfiguring a registered alarm system requires
    `expected_alarm_system_version` carrying the client's last observed
    `version` of that `AlarmSystem`, and a mismatch is rejected with
    `ERR_STALE_ALARM_SYSTEM_VERSION` (HTTP 412)." It adds: "it is refused
    because the submitted field set would silently overwrite a change another
    writer already applied, for example re-enabling enhanced call verification
    that was just switched off." PRD §3.3 states: "A registered system may
    later be reconfigured — its monitoring company, its `ecv_enabled` flag, its
    `verified_response_mode` or its `zone_count` — by a write that carries
    `expected_alarm_system_version` and, on success, bumps that system's
    `version` by 1 and refreshes the enhanced-call-verification requirement
    derived from it."

    Two clerks read the same system revision. The first sets zone_count to 9
    and is accepted. The second wants to clear ecv_enabled — a field the winner
    never touched — but its revision is stale, so it is refused at HTTP 412:
    zone_count stays 9, ecv_enabled stays true, and the system revision has
    advanced exactly once across both attempts.

    Design: Corner/cross_cutting_complexity_layers/occ_stale_alarm_system_version_blocks_a_second_reconfiguration
    """
    bundle = X.setup_program_baseline(api, clock=CLOCK_DETERMINE)
    system_id = bundle.system_id
    permit_before = X.get_permit(api, bundle.permit_id)
    site_before = X.get_site(api, bundle.site_id)

    read_version = X.system_version(api, system_id)

    winner = api.patch_alarm_system(
        system_id,
        {"expected_alarm_system_version": read_version, "zone_count": 9},
        U.PERMIT_CLERK,
    )
    validate_success(winner, 200)
    after_winner = X.get_system(api, system_id)
    assert after_winner["zone_count"] == 9, (
        f"the accepted reconfiguration must have stored zone_count 9, got {after_winner['zone_count']}"
    )
    assert after_winner["version"] == read_version + 1, (
        "an accepted reconfiguration must lift the system revision by one, "
        f"was {read_version}, now {after_winner['version']}"
    )

    loser = api.patch_alarm_system(
        system_id,
        {"expected_alarm_system_version": read_version, "ecv_enabled": False},
        U.PERMIT_CLERK,
    )
    validate_error(loser, E.ERR_STALE_ALARM_SYSTEM_VERSION, expected_status=412)

    final = X.get_system(api, system_id)
    assert final["zone_count"] == 9, "the winner's zone_count must survive the refused write"
    assert final["ecv_enabled"] is True, (
        f"the refused write must not have cleared ecv_enabled, got {final['ecv_enabled']!r}"
    )
    A.assert_version_unchanged(after_winner, final)
    A.assert_version_unchanged(permit_before, X.get_permit(api, bundle.permit_id))
    site_after = X.get_site(api, bundle.site_id)
    assert site_after["ecv_callable_contact_count"] == site_before["ecv_callable_contact_count"] == 2, (
        "the callable roster count must be untouched by the refused reconfiguration"
    )


def test_stale_alarm_permit_version_blocks_a_second_renewal(api):
    """A second renewal on a stale permit revision answers the revision guard, not the window rule.

    PRD §3.3 states: "The request supplies `expected_alarm_permit_version`,
    which must equal the permit's current `version`, else
    `ERR_STALE_ALARM_PERMIT_VERSION`." PRD §2.10 states: "Every one of these is
    checked before any state precondition, so a caller working from a stale
    read learns that fact rather than receiving a state complaint." PRD §3.3
    also states: "On success the permit returns to `ACTIVE` with `term_start_at`
    set to the logical clock, `term_end_at` recomputed as that instant plus
    `permit_term_days`, `grace_through_at` recomputed from the new term end,
    `renewal_count` increased by 1, `last_renewed_at` stamped, and
    `new_installation_grace_through` left null."

    The permit is issued 2026-08-01 for a 365-day term, so the nightly run at
    2027-07-05 has already moved it to RENEWAL_DUE. Both callers read the same
    revision; the first renewal is accepted and issues one PERMIT_RENEWAL_FEE
    invoice of 3000 subtotal plus the administrative fee, which is 5% of 3000,
    that is 150, clamped up to the 500-cent floor, for an assessed 3500. The
    second renewal carries the pre-renewal revision and is refused at HTTP 412
    rather than with a complaint about the renewal window, leaving
    renewal_count at 1 and a single renewal invoice.

    Design: Corner/cross_cutting_complexity_layers/occ_stale_alarm_permit_version_blocks_a_second_renewal
    """
    bundle = X.setup_program_baseline(api, clock=CLOCK_DETERMINE)
    permit_id = bundle.permit_id

    X.set_clock(api, "2027-07-05T00:00:00Z")
    X.run_nightly(api)
    A.assert_status(X.get_permit(api, permit_id), "RENEWAL_DUE")

    read_version = X.permit_version(api, permit_id)

    first = api.renew_permit(
        permit_id, {"expected_alarm_permit_version": read_version}, bundle.holder_headers
    )
    validate_success(first, 200)
    after_first = X.get_permit(api, permit_id)
    A.assert_status(after_first, "ACTIVE")
    assert after_first["renewal_count"] == 1, (
        f"renewal_count must stand at 1 after one accepted renewal, got {after_first['renewal_count']}"
    )
    assert after_first["version"] == read_version + 1, (
        "an accepted renewal must lift the permit revision by one, "
        f"was {read_version}, now {after_first['version']}"
    )
    extended_term_end = after_first["term_end_at"]

    second = api.renew_permit(
        permit_id, {"expected_alarm_permit_version": read_version}, bundle.holder_headers
    )
    validate_error(second, E.ERR_STALE_ALARM_PERMIT_VERSION, expected_status=412)

    final = X.get_permit(api, permit_id)
    A.assert_version_unchanged(after_first, final)
    assert final["renewal_count"] == 1, "the refused renewal must not have advanced renewal_count"
    assert final["term_end_at"] == extended_term_end, (
        "the refused renewal must not have extended the term a second time"
    )

    renewals = X.invoices_of_site(api, bundle.site_id, kind="PERMIT_RENEWAL_FEE")
    assert len(renewals) == 1, (
        f"exactly one renewal invoice must exist, got {len(renewals)}"
    )
    A.assert_invoice_totals(
        renewals[0], subtotal_cents=3000, admin_fee_cents=500, assessed_cents=3500
    )


def test_stale_false_alarm_incident_version_blocks_an_appeal_filing(api):
    """A refiling that echoes the pre-appeal incident revision is refused even though the determination reads the same.

    PRD §2.8 states: "Filing an appeal requires
    `expected_false_alarm_incident_version` to equal the contested incident's
    current `version`, failing with
    `ERR_STALE_FALSE_ALARM_INCIDENT_VERSION`." PRD §3.6 states: "The contested
    incident moves from `COUNTED` to `APPEALED`, its `appeal_count` and
    `version` each rise by 1" and "Withdrawal from either state returns the
    incident from `APPEALED` to `COUNTED` and resumes dunning on its invoice".

    The appellant's own first appeal, and its withdrawal, moved the incident
    twice, so the determination reads the same COUNTED, occurrence index 1 and
    zero fee as before but at a strictly higher revision. The refiling that
    echoes the pre-appeal revision is therefore refused at HTTP 412, leaving
    exactly one WITHDRAWN appeal, while the same body with a freshly read
    revision is accepted.

    Design: Corner/cross_cutting_complexity_layers/occ_stale_false_alarm_incident_version_blocks_an_appeal_filing
    """
    bundle = _commercial_premises(api)
    incident = X.create_counted_incident(api, bundle, bundle.system_id, OCCURRENCES[0])
    incident_id = incident.incident_id

    determined = X.get_incident(api, incident_id)
    A.assert_status(determined, "COUNTED")
    assert determined["occurrence_index"] == 1, (
        f"the first chargeable alarm takes occurrence index 1, got {determined['occurrence_index']}"
    )
    A.assert_money_cents(determined["assessed_fee_cents"], 0, "assessed_fee_cents")
    stale_version = determined["version"]

    appeal_id = X.file_appeal(api, bundle, incident_id, grounds="WRONG_CAUSE_CODE")
    withdrawal = api.withdraw_appeal(appeal_id, bundle.holder_headers)
    validate_success(withdrawal, 200)
    A.assert_status(X.get_appeal(api, appeal_id), "WITHDRAWN")

    refile = api.create_appeal(
        F.appeal_payload(
            incident_id,
            grounds="COUNTING_ERROR",
            narrative="Second filing prepared from the pre-appeal view of the incident.",
            expected_false_alarm_incident_version=stale_version,
        ),
        bundle.holder_headers,
    )
    validate_error(refile, E.ERR_STALE_FALSE_ALARM_INCIDENT_VERSION, expected_status=412)

    rows = A.assert_total_count(
        api.list_appeals(U.PROGRAM_ADMIN, {"false_alarm_incident_id": incident_id}), 1
    )
    assert rows[0]["id"] == appeal_id, "no second appeal row may have been created"
    A.assert_status(rows[0], "WITHDRAWN")

    after = X.get_incident(api, incident_id)
    A.assert_status(after, "COUNTED")
    assert after["occurrence_index"] == 1, "the withdrawal restores occurrence index 1"
    A.assert_money_cents(after["assessed_fee_cents"], 0, "assessed_fee_cents")
    assert after["version"] > stale_version, (
        "the appeal and its withdrawal must have advanced the incident revision past "
        f"{stale_version}, got {after['version']}"
    )

    accepted = api.create_appeal(
        F.appeal_payload(
            incident_id,
            grounds="COUNTING_ERROR",
            narrative="Second filing prepared from the pre-appeal view of the incident.",
            expected_false_alarm_incident_version=after["version"],
        ),
        bundle.holder_headers,
    )
    validate_success(accepted, 201)
    A.assert_status(get_success_data(accepted), "FILED")


def test_stale_hearing_docket_version_blocks_a_second_scheduling(api):
    """A second seating from a pre-booking docket revision is refused although the session has spare capacity.

    PRD §2.8 states: "Scheduling an appeal onto a docket requires
    `expected_hearing_docket_version` to equal that docket's current `version`,
    failing with `ERR_STALE_HEARING_DOCKET_VERSION`." PRD §3.6 states: "On
    success the appeal moves to `SCHEDULED` with its `hearing_docket_id` set,
    and the docket's `scheduled_appeal_count` and `version` each rise by 1."

    The session seats up to four appeals and only one seat is taken, so the
    second seating is well within capacity and would be accepted on a fresh
    read. Because it echoes the revision the docket carried before the first
    booking, it is refused at HTTP 412: the seat count stays 1, the docket stays
    OPEN, the second appeal stays FILED with no docket, and re-reading the
    docket and resubmitting the same body seats it as the second of four.

    Design: Corner/cross_cutting_complexity_layers/occ_stale_hearing_docket_version_blocks_a_second_scheduling
    """
    bundle = _commercial_premises(api, system_count=2)
    first_incident = X.create_counted_incident(api, bundle, bundle.system_ids[0], OCCURRENCES[0])
    second_incident = X.create_counted_incident(api, bundle, bundle.system_ids[1], OCCURRENCES[1])

    appeal_one = X.file_appeal(api, bundle, first_incident.incident_id)
    appeal_two = X.file_appeal(api, bundle, second_incident.incident_id, grounds="EXEMPT_CAUSE")

    docket_id = X.create_docket(api, "2026-10-05T09:00:00Z", "2026-10-05T11:00:00Z", capacity=4)
    read_version = X.docket_version(api, docket_id)

    seated = api.schedule_appeal(
        appeal_one,
        {"hearing_docket_id": docket_id, "expected_hearing_docket_version": read_version},
        U.HEARING_OFFICER,
    )
    validate_success(seated, 200)
    after_first = A.data_of(api.get_hearing_docket(docket_id, U.HEARING_OFFICER))
    assert after_first["scheduled_appeal_count"] == 1, (
        f"the first seating must leave one seat taken, got {after_first['scheduled_appeal_count']}"
    )
    assert after_first["version"] == read_version + 1, (
        "an accepted seating must lift the docket revision by one, "
        f"was {read_version}, now {after_first['version']}"
    )

    stale = api.schedule_appeal(
        appeal_two,
        {"hearing_docket_id": docket_id, "expected_hearing_docket_version": read_version},
        U.HEARING_OFFICER,
    )
    validate_error(stale, E.ERR_STALE_HEARING_DOCKET_VERSION, expected_status=412)

    unchanged = A.data_of(api.get_hearing_docket(docket_id, U.HEARING_OFFICER))
    assert unchanged["scheduled_appeal_count"] == 1, (
        "the refused seating must not have taken a seat, got "
        f"{unchanged['scheduled_appeal_count']}"
    )
    A.assert_status(unchanged, "OPEN")
    A.assert_version_unchanged(after_first, unchanged)

    still_filed = X.get_appeal(api, appeal_two)
    A.assert_status(still_filed, "FILED")
    assert still_filed["hearing_docket_id"] is None, (
        "the refused seating must leave the appeal unscheduled, got "
        f"{still_filed['hearing_docket_id']!r}"
    )

    retry = api.schedule_appeal(
        appeal_two,
        {"hearing_docket_id": docket_id, "expected_hearing_docket_version": unchanged["version"]},
        U.HEARING_OFFICER,
    )
    validate_success(retry, 200)
    A.assert_status(get_success_data(retry), "SCHEDULED")
    final = A.data_of(api.get_hearing_docket(docket_id, U.HEARING_OFFICER))
    assert final["scheduled_appeal_count"] == 2 and final["capacity"] == 4, (
        "the refreshed seating must take the second of four seats, got "
        f"{final['scheduled_appeal_count']} of {final['capacity']}"
    )


def test_every_accepted_write_bumps_the_version_and_the_refreshed_retry_succeeds(api):
    """A revision advances by exactly one per accepted write and not at all on a refused one.

    PRD §2.4 states: "Most resources additionally carry `updated_at`, refreshed
    on every mutation, and `version`, an integer that starts at 1 on creation
    and increments by exactly 1 on every mutation of that row." PRD §2.8
    states: "The client reads the parent, notes its `version`, and sends that
    value back with the write; if the parent's current `version` no longer
    equals the submitted value, the write is refused with HTTP 412 and the
    parent is left untouched."

    Three writes are attempted against one registered system and two are
    accepted. The first takes zone_count to 9 and lifts the revision once. The
    second replays the original revision and is refused, so a fresh read shows
    the revision unmoved and zone_count still 9. The third echoes that fresh
    revision and is accepted, landing zone_count at 10 with the revision
    exactly one greater — the refusal burned no revision.

    Design: Corner/cross_cutting_complexity_layers/occ_every_accepted_write_bumps_the_version_and_the_refreshed_retry_succeeds
    """
    bundle = X.setup_program_baseline(api, clock=CLOCK_DETERMINE)
    system_id = bundle.system_id
    permit_before = X.get_permit(api, bundle.permit_id)
    site_before = X.get_site(api, bundle.site_id)

    read_version = X.system_version(api, system_id)

    accepted = api.patch_alarm_system(
        system_id,
        {"expected_alarm_system_version": read_version, "zone_count": 9},
        U.PERMIT_CLERK,
    )
    validate_success(accepted, 200)
    first_state = get_success_data(accepted)
    assert first_state["zone_count"] == 9, (
        f"the first accepted write must store zone_count 9, got {first_state['zone_count']}"
    )
    assert first_state["version"] == read_version + 1, (
        f"the revision must move from {read_version} to {read_version + 1}, got {first_state['version']}"
    )

    refused = api.patch_alarm_system(
        system_id,
        {"expected_alarm_system_version": read_version, "zone_count": 10},
        U.PERMIT_CLERK,
    )
    validate_error(refused, E.ERR_STALE_ALARM_SYSTEM_VERSION, expected_status=412)

    fresh = X.get_system(api, system_id)
    A.assert_version_unchanged(first_state, fresh)
    assert fresh["zone_count"] == 9, (
        f"the refused write must leave zone_count at 9, got {fresh['zone_count']}"
    )

    retry = api.patch_alarm_system(
        system_id,
        {"expected_alarm_system_version": fresh["version"], "zone_count": 10},
        U.PERMIT_CLERK,
    )
    validate_success(retry, 200)
    final = get_success_data(retry)
    assert final["zone_count"] == 10, (
        f"the refreshed retry must store zone_count 10, got {final['zone_count']}"
    )
    assert final["version"] == read_version + 2, (
        "two accepted writes and one refusal must leave the revision exactly two above the "
        f"first read of {read_version}, got {final['version']}"
    )

    A.assert_version_unchanged(permit_before, X.get_permit(api, bundle.permit_id))
    site_after = X.get_site(api, bundle.site_id)
    for counter in (
        "chargeable_count_window",
        "chargeable_count_rolling_365",
        "chargeable_count_permit_year",
        "unpermitted_system_count",
        "ecv_callable_contact_count",
        "outstanding_balance_cents",
    ):
        assert site_after[counter] == site_before[counter], (
            f"no reconfiguration may move the premises' {counter}: was "
            f"{site_before[counter]}, now {site_after[counter]}"
        )


def test_probation_posture_flips_at_exactly_the_fourth_chargeable_alarm(api):
    """Three chargeable alarms leave police response active and the fourth flips the premises onto probation.

    PRD §3.5 states: "Otherwise, if `chargeable_count_window` is at or above
    `probation_threshold_count`, the posture is `RESPONSE_PROBATION`." It also
    states: "Both thresholds are inclusive: with the defaults, a window count
    of 4 puts the premises on probation and 3 does not, and a count of 6
    proposes a suspension while 5 does not." On pricing it states: "the tier
    base is the `base_fee_cents` of the single `fee_tiers` entry whose
    `from_index` is at or below the index and whose `to_index` is either null or
    at or above the index" and "the tier base is multiplied by all three
    factors together and that single product is rounded half up to a whole
    cent."

    The fourth chargeable alarm takes occurrence index 4, whose marginal tier
    base is 25000, times the COMMERCIAL occupancy multiplier of 1.50, for 37500
    cents. The window count reaches the inclusive probation threshold of 4 while
    staying below the suspension threshold of 6, so the posture becomes
    RESPONSE_PROBATION with no enforcement order in existence.

    Design: Corner/cross_cutting_complexity_layers/rate_threshold_probation_posture_flips_at_exactly_the_fourth_chargeable_alarm
    """
    bundle = _commercial_premises(api, system_count=4, contact_count=3)
    _counted_incidents(api, bundle, 3)
    fourth = X.create_reported_incident(api, bundle, bundle.system_ids[3], OCCURRENCES[3])
    permit_before = X.get_permit(api, bundle.permit_ids[0])

    at_three = X.get_summary(api, bundle.site_id)
    assert at_three["chargeable_count_window"] == 3, (
        f"three chargeable alarms must read as a window count of 3, got {at_three['chargeable_count_window']}"
    )
    assert at_three["response_status"] == "RESPONSE_ACTIVE", (
        "one short of the inclusive threshold the posture must still be RESPONSE_ACTIVE, got "
        f"{at_three['response_status']!r}"
    )

    ruled = X.determine_counted(api, fourth.incident_id)
    assert ruled["occurrence_index"] == 4, (
        f"the fourth chargeable alarm takes occurrence index 4, got {ruled['occurrence_index']}"
    )
    A.assert_money_cents(ruled["assessed_fee_cents"], 37500, "assessed_fee_cents")
    A.assert_fee_basis(
        ruled["fee_basis"],
        tier_base_cents=25000,
        occupancy_multiplier=1.50,
        non_ecv_surcharge_applied=False,
        unpermitted_multiplier_applied=False,
        aggravation_cents=0,
        cap_applied=False,
    )

    at_four = X.get_summary(api, bundle.site_id)
    assert at_four["chargeable_count_window"] == 4, (
        f"the fourth ruling must lift the window count to 4, got {at_four['chargeable_count_window']}"
    )
    assert at_four["response_status"] == "RESPONSE_PROBATION", (
        f"a window count of 4 puts the premises on probation, got {at_four['response_status']!r}"
    )

    A.assert_total_count(
        api.list_suspension_orders(U.PROGRAM_ADMIN, {"alarm_site_id": bundle.site_id}), 0
    )
    A.assert_version_unchanged(permit_before, X.get_permit(api, bundle.permit_ids[0]))


def test_suspension_auto_proposal_fires_at_exactly_the_sixth_chargeable_alarm(api):
    """The sixth chargeable alarm auto-proposes an enforcement order inside the same ruling request.

    PRD §3.5 states: "And when `chargeable_count_window` reaches or exceeds
    `suspension_threshold_count`, an enforcement order is auto-proposed for the
    premises: a suspension order in `PROPOSED` with `basis` of
    `EXCESSIVE_FALSE_ALARMS`, its `triggering_incident_id` set to this incident,
    `effective_from` at the logical clock plus 10 days and `effective_through`
    at 30 days after that." It also states: "Both thresholds are inclusive:
    with the defaults, a window count of 4 puts the premises on probation and 3
    does not, and a count of 6 proposes a suspension while 5 does not." On
    posture it states: "If the premises has a suspension order in `EFFECTIVE`
    or `REINSTATEMENT_PENDING` whose closed interval contains the current
    instant, the posture is `RESPONSE_SUSPENDED`."

    At five chargeable alarms no order exists at all, even though the fifth was
    priced from the 40000-cent tier times 1.50 for 60000 cents and the premises
    is already on probation. The sixth ruling creates exactly one PROPOSED
    order whose sequence is the premises' lifted-suspension count of zero plus
    one, effective from the clock of 2026-09-20T01:00:00Z plus ten days, that is
    2026-09-30T01:00:00Z, through thirty days after that, 2026-10-30T01:00:00Z.
    A merely proposed order does not withdraw response, so the posture stays
    RESPONSE_PROBATION.

    Design: Corner/cross_cutting_complexity_layers/rate_threshold_suspension_auto_proposal_fires_at_exactly_the_sixth_chargeable_alarm
    """
    bundle = _commercial_premises(api, system_count=6, contact_count=3)
    counted = _counted_incidents(api, bundle, 5)
    A.assert_money_cents(
        X.get_incident(api, counted[4].incident_id)["assessed_fee_cents"], 60000, "assessed_fee_cents"
    )
    sixth = X.create_reported_incident(api, bundle, bundle.system_ids[5], OCCURRENCES[5])

    at_five = X.get_summary(api, bundle.site_id)
    assert at_five["response_status"] == "RESPONSE_PROBATION", (
        f"five chargeable alarms leave the premises on probation, got {at_five['response_status']!r}"
    )
    A.assert_total_count(
        api.list_suspension_orders(
            U.PROGRAM_ADMIN,
            {"alarm_site_id": bundle.site_id, "status": "PROPOSED", "page": 1, "per_page": 25},
        ),
        0,
    )

    ruling = api.determine_incident(
        sixth.incident_id, F.determination_payload("COUNTED"), U.REVIEW_OFFICER
    )
    validate_success(ruling, 200)
    assert get_success_data(ruling)["occurrence_index"] == 6, (
        "the sixth chargeable alarm takes occurrence index 6, got "
        f"{get_success_data(ruling)['occurrence_index']}"
    )

    orders = A.assert_total_count(
        api.list_suspension_orders(
            U.PROGRAM_ADMIN,
            {"alarm_site_id": bundle.site_id, "status": "PROPOSED", "page": 1, "per_page": 25},
        ),
        1,
    )
    order = orders[0]
    A.assert_status(order, "PROPOSED")
    assert order["basis"] == "EXCESSIVE_FALSE_ALARMS", (
        f"the auto-proposal is based on excessive false alarms, got {order['basis']!r}"
    )
    assert order["triggering_incident_id"] == sixth.incident_id, (
        "the auto-proposal must name the ruling incident as its trigger, got "
        f"{order['triggering_incident_id']!r}"
    )
    assert order["suspension_sequence"] == 1, (
        f"the first order at the premises carries sequence 1, got {order['suspension_sequence']}"
    )
    assert _at_second(order["effective_from"]) == "2026-09-30T01:00:00Z", (
        f"effective_from must be the clock plus ten days, got {order['effective_from']!r}"
    )
    assert _at_second(order["effective_through"]) == "2026-10-30T01:00:00Z", (
        f"effective_through must be thirty days after that, got {order['effective_through']!r}"
    )

    after = X.get_summary(api, bundle.site_id)
    assert after["response_status"] == "RESPONSE_PROBATION", (
        "a proposed order does not withdraw response, so the posture stays on probation, got "
        f"{after['response_status']!r}"
    )


def test_rolling_window_reset_returns_the_posture_to_active(api):
    """Once every counted alarm ages out of the rolling year the posture returns to active with no write at all.

    PRD §3.5 states: "The premises' own counters use the same two definitions
    but evaluated at the logical clock rather than at any one incident's
    instant: `chargeable_count_rolling_365` counts chargeable incidents in the
    365 days up to now, `chargeable_count_permit_year` counts them from the
    current term start up to now, and `chargeable_count_window` is whichever of
    the two the governing `counting_window_mode` selects." It also states:
    "Otherwise, if `chargeable_count_window` is at or above
    `probation_threshold_count`, the posture is `RESPONSE_PROBATION`. Otherwise
    it is `RESPONSE_ACTIVE`." PRD §2.4 states of the summary: "The one
    documented exception is the read-only false alarm summary on a premises: it
    recomputes and returns the posture and balance figures at the current
    logical clock without persisting a version bump."

    Four chargeable alarms occurring 2026-09-15 through 2026-09-18 put the
    premises on probation. Moving the clock to 2027-09-20 leaves every one of
    them more than 365 days back, so both rolling counters collapse to 0 and the
    posture returns to RESPONSE_ACTIVE without any incident being rewritten. The
    money is computed from different inputs and does not reset: the four
    permit-issue invoices of 5500 each, the third alarm's 15750 and the fourth
    alarm's 39375 leave 77125 cents outstanding, at or above the 50000-cent
    blocking threshold, so the renewal block stands.

    Design: Corner/cross_cutting_complexity_layers/rate_threshold_rolling_window_reset_returns_the_posture_to_active
    """
    bundle = _commercial_premises(api, system_count=4, contact_count=3)
    incidents = _counted_incidents(api, bundle, 4)

    on_probation = X.get_summary(api, bundle.site_id)
    assert on_probation["response_status"] == "RESPONSE_PROBATION", (
        f"four chargeable alarms put the premises on probation, got {on_probation['response_status']!r}"
    )

    X.set_clock(api, "2027-09-20T00:00:00Z")

    summary = X.get_summary(api, bundle.site_id)
    assert summary["chargeable_count_window"] == 0, (
        f"every occurrence has aged out of the window, got {summary['chargeable_count_window']}"
    )
    assert summary["chargeable_count_rolling_365"] == 0, (
        f"the rolling-year counter must collapse to 0, got {summary['chargeable_count_rolling_365']}"
    )
    assert summary["response_status"] == "RESPONSE_ACTIVE", (
        f"an empty window returns the posture to RESPONSE_ACTIVE, got {summary['response_status']!r}"
    )
    assert summary["renewal_block_active"] is True, (
        "the unpaid fees keep the renewal block on, got "
        f"{summary['renewal_block_active']!r}"
    )
    A.assert_money_cents(summary["outstanding_balance_cents"], 77125, "outstanding_balance_cents")

    for position, incident in enumerate(incidents, start=1):
        row = X.get_incident(api, incident.incident_id)
        A.assert_status(row, "COUNTED")
        assert row["occurrence_index"] == position, (
            f"incident {position} must keep occurrence index {position}, got {row['occurrence_index']}"
        )
    A.assert_money_cents(
        X.get_incident(api, incidents[3].incident_id)["assessed_fee_cents"],
        37500,
        "assessed_fee_cents",
    )


def test_determination_runs_four_levels_inside_one_request(api):
    """One chargeable ruling prices the alarm, bills it, rolls up the premises and auto-proposes an order.

    PRD §3.5 states: "It then sets `determination` to `COUNTED`, stamps
    `determined_at` with the logical clock and `determined_by_user_id` with the
    acting `X-User-ID`, assigns the occurrence numbering, prices the incident,
    and bills it." It also states: "the cap is treated as applied only when the
    rounded amount is **strictly greater** than `per_incident_fee_cap_cents`, so
    an amount exactly equal to the cap passes through unchanged and is not
    flagged as capped; the amount is then clipped to the cap; and finally, if a
    suspension order for the premises in `EFFECTIVE` or `REINSTATEMENT_PENDING`
    covers the incident's occurrence instant within its closed interval from
    `effective_from` through `effective_through`, the flat
    `suspension_period_aggravation_cents` is added **after** the clip." It adds:
    "The premises' `chargeable_count_rolling_365`,
    `chargeable_count_permit_year`, `chargeable_count_window`,
    `lifetime_assessed_cents`, `outstanding_balance_cents`,
    `renewal_block_active` and `response_status` are then all recomputed."

    The sixth alarm prices at the 75000-cent tier times the COMMERCIAL 1.50
    multiplier, that is 112500, which is strictly greater than the 100000-cent
    cap, so the fee is clipped to 100000 with no aggravation, because the order
    the same request proposes is only PROPOSED and never covers the occurrence.
    Its invoice carries the single capped base line of 100000 plus the
    administrative fee of 5% clamped down to the 5000-cent ceiling, an assessed
    105000, and a due date thirty days past the ruling instant. The premises'
    outstanding balance rises by exactly that 105000.

    Design: Corner/cross_cutting_complexity_layers/cascading_determination_runs_four_levels_inside_one_request
    """
    bundle = _commercial_premises(api, system_count=6, contact_count=3)
    _counted_incidents(api, bundle, 5)
    sixth = X.create_reported_incident(api, bundle, bundle.system_ids[5], OCCURRENCES[5])

    before = X.get_site(api, bundle.site_id)

    ruled = X.determine_counted(api, sixth.incident_id)
    A.assert_status(ruled, "COUNTED")
    assert ruled["occurrence_index"] == 6, (
        f"the sixth chargeable alarm takes occurrence index 6, got {ruled['occurrence_index']}"
    )
    A.assert_money_cents(ruled["assessed_fee_cents"], 100000, "assessed_fee_cents")
    A.assert_fee_basis(
        ruled["fee_basis"],
        tier_base_cents=75000,
        occupancy_multiplier=1.50,
        non_ecv_surcharge_applied=False,
        unpermitted_multiplier_applied=False,
        aggravation_cents=0,
        cap_applied=True,
    )

    invoice = X.invoice_for_incident(api, sixth.incident_id)
    A.assert_invoice_totals(
        invoice, subtotal_cents=100000, admin_fee_cents=5000, assessed_cents=105000
    )
    A.assert_outstanding_identity(invoice)
    assert _at_second(invoice["due_on"]) == "2026-10-20T01:00:00Z", (
        f"the invoice falls due thirty days after issuance, got {invoice['due_on']!r}"
    )
    codes = [line["code"] for line in invoice["line_items"]]
    assert codes == ["FALSE_ALARM_BASE"], (
        "a proposed order applies no aggravation, so the invoice carries the base line alone, got "
        f"{codes}"
    )
    A.assert_money_cents(
        invoice["line_items"][0]["extended_cents"], 100000, "line extended_cents"
    )

    after = X.get_site(api, bundle.site_id)
    A.assert_money_cents(
        after["outstanding_balance_cents"],
        before["outstanding_balance_cents"] + 105000,
        "outstanding_balance_cents",
    )
    A.assert_money_cents(
        after["lifetime_assessed_cents"],
        before["lifetime_assessed_cents"] + 105000,
        "lifetime_assessed_cents",
    )
    assert after["renewal_block_active"] is True, (
        f"the new assessment keeps the renewal block on, got {after['renewal_block_active']!r}"
    )

    order = A.single(
        api.list_suspension_orders(
            U.PROGRAM_ADMIN, {"alarm_site_id": bundle.site_id, "status": "PROPOSED"}
        )
    )
    assert order["triggering_incident_id"] == sixth.incident_id, (
        "the auto-proposal must name the ruling incident, got "
        f"{order['triggering_incident_id']!r}"
    )
    assert X.get_summary(api, bundle.site_id)["response_status"] == "RESPONSE_PROBATION", (
        "an unserved order leaves the premises on probation rather than suspended"
    )


def test_appeal_grant_reverses_the_chain_and_vacates_the_order(api):
    """Granting the appeal against the third alarm renumbers, re-prices, credits the paid money and vacates the order.

    PRD §3.6 states: "Hop one: the incident moves from `APPEALED` to the
    terminal `EXEMPT_BY_APPEAL`, with `determination` set to `EXEMPT`,
    `exempt_cause_code` taken from the ruling, `occurrence_index` set to null and
    `assessed_fee_cents` set to 0. Hop two: because the incident left the
    chargeable set, the premises' chargeable counters decrement and every
    remaining chargeable incident at that premises — those in `COUNTED` or
    `APPEALED` — is renumbered contiguously in order of occurrence instant
    ascending then creation instant ascending, and its fee re-derived at its new
    tier. Hop three: because a renumbered incident's assessed fee changed, its
    invoice is re-assessed, `assessed_cents` recomputed, and any `paid_cents`
    above the new `assessed_cents` moved into the premises' `credit_balance_cents`.
    Hop four: because the premises' `chargeable_count_window` has fallen below
    `suspension_threshold_count`, every suspension order for that premises in
    `PROPOSED`, `EFFECTIVE` or `REINSTATEMENT_PENDING` moves to `VACATED` and
    `response_status` is recomputed."

    Six chargeable alarms at a COMMERCIAL premises price at 0, 0, 15000, 37500,
    60000 and the capped 100000. The third alarm's 15750-cent invoice is paid in
    full, and its appeal is granted. Renumbering drops each higher alarm one
    tier: the fourth becomes index 3 at 15000, the fifth index 4 at 37500 and the
    sixth index 5 at 60000 with the cap no longer biting, so their invoices
    re-assess to 15750, 39375 and 63000. The 15750 already collected lands in the
    premises' credit balance, the window count falls from six to five so the
    proposed order is vacated, and the posture settles on probation.

    Design: Corner/cross_cutting_complexity_layers/cascading_appeal_grant_reverses_the_chain_and_vacates_the_order
    """
    bundle = _commercial_premises(api, system_count=6, contact_count=3)
    incidents = _counted_incidents(api, bundle, 6)

    third_invoice = X.invoice_for_incident(api, incidents[2].incident_id)
    A.assert_invoice_totals(third_invoice, assessed_cents=15750)
    X.post_payment(
        api,
        bundle,
        15750,
        CLOCK_DETERMINE,
        allocation_mode="EXPLICIT",
        method="ACH",
        explicit_allocations=[
            {"penalty_invoice_id": third_invoice["id"], "amount_cents": 15750}
        ],
    )
    A.assert_invoice_totals(
        X.get_invoice(api, third_invoice["id"]), paid_cents=15750, payment_status="PAID"
    )

    order = A.single(
        api.list_suspension_orders(
            U.PROGRAM_ADMIN, {"alarm_site_id": bundle.site_id, "status": "PROPOSED"}
        )
    )

    appeal_id, _docket_id = X.create_heard_appeal(
        api,
        bundle,
        incidents[2].incident_id,
        session_start="2026-10-05T14:00:00Z",
        session_end="2026-10-05T16:00:00Z",
        grounds="EXEMPT_CAUSE",
    )
    decided = X.decide_appeal(
        api,
        appeal_id,
        "GRANTED",
        findings="The utility outage is an exempt cause; occurrence 3 is struck and the record renumbered.",
        exempt_cause_code="UTILITY_POWER_FAILURE",
    )
    assert decided["decision"] == "GRANTED", (
        f"the ruling must be recorded as granted, got {decided['decision']!r}"
    )

    exempted = X.get_incident(api, incidents[2].incident_id)
    A.assert_status(exempted, "EXEMPT_BY_APPEAL")
    assert exempted["occurrence_index"] is None, (
        f"an exempted alarm carries no occurrence index, got {exempted['occurrence_index']}"
    )
    A.assert_money_cents(exempted["assessed_fee_cents"], 0, "assessed_fee_cents")
    A.assert_invoice_totals(X.get_invoice(api, third_invoice["id"]), outstanding_cents=0)

    for position, (incident, index, fee, assessed) in enumerate(
        [
            (incidents[3], 3, 15000, 15750),
            (incidents[4], 4, 37500, 39375),
            (incidents[5], 5, 60000, 63000),
        ],
        start=4,
    ):
        row = X.get_incident(api, incident.incident_id)
        A.assert_status(row, "COUNTED")
        assert row["occurrence_index"] == index, (
            f"alarm {position} must renumber to index {index}, got {row['occurrence_index']}"
        )
        A.assert_money_cents(row["assessed_fee_cents"], fee, "assessed_fee_cents")
        A.assert_invoice_totals(
            X.invoice_for_incident(api, incident.incident_id), assessed_cents=assessed
        )
    A.assert_fee_basis(
        X.get_incident(api, incidents[5].incident_id)["fee_basis"],
        tier_base_cents=40000,
        cap_applied=False,
    )

    A.assert_status(X.get_order(api, order["id"]), "VACATED")

    summary = X.get_summary(api, bundle.site_id)
    assert summary["chargeable_count_window"] == 5, (
        f"the window count must fall from six to five, got {summary['chargeable_count_window']}"
    )
    assert summary["response_status"] == "RESPONSE_PROBATION", (
        f"five chargeable alarms leave the premises on probation, got {summary['response_status']!r}"
    )
    A.assert_money_cents(summary["credit_balance_cents"], 15750, "credit_balance_cents")
    A.assert_money_cents(
        summary["outstanding_balance_cents"], 151125, "outstanding_balance_cents"
    )


def test_counting_window_modes_diverge_on_identical_alarm_data(api):
    """Both counting variants are maintained side by side, and a renewal makes them disagree on the same rows.

    PRD §3.5 states: "Under `PERMIT_YEAR`, the window is anchored on the permit
    term that contains the incident: the term start is taken from the premises
    permit whose closed interval from `term_start_at` through `grace_through_at`
    contains the incident's occurrence instant, taking the greatest such
    `term_start_at` when several permits qualify and breaking any remaining tie
    by earliest `created_at`; the window then includes every chargeable incident
    at the premises whose occurrence instant is at or after that term start and
    at or before this incident's occurrence instant, again both bounds
    inclusive." It also states: "Under `PERMIT_YEAR` the window restarts at every
    renewal, so four incidents that would produce an index of 4 — and its
    25000-cent tier — under the rolling variant instead produce an index of 1,
    which is free under the allowance, if a renewal falls between them. Identical
    data, different fee." And: "`chargeable_count_rolling_365` counts chargeable
    incidents in the 365 days up to now, `chargeable_count_permit_year` counts
    them from the current term start up to now, and `chargeable_count_window` is
    whichever of the two the governing `counting_window_mode` selects."

    Two chargeable alarms in June 2027 sit inside the original term, a renewal
    on 2027-07-05 opens a new term, and a third alarm on 2027-08-16 falls inside
    it. Under the governing PERMIT_YEAR variant that third alarm is occurrence 1
    and free under the two-alarm allowance, so no fee invoice is raised at all.
    The rolling variant, maintained alongside, still counts all three; had it
    governed, the same alarm would have been occurrence 3 at the 10000-cent tier
    times the RESIDENTIAL multiplier of 1.00 plus the 500-cent minimum
    administrative fee, so the mode choice is worth 10500 cents on identical
    data.

    Design: Corner/cross_cutting_complexity_layers/dual_variant_counting_window_modes_diverge_on_identical_alarm_data
    """
    bundle = X.setup_program_baseline(
        api,
        clock="2027-06-20T05:00:00Z",
        schedule_overrides={"counting_window_mode": "PERMIT_YEAR"},
        system_count=3,
    )

    first = X.create_counted_incident(api, bundle, bundle.system_ids[0], "2027-06-20T04:00:00Z")
    assert X.get_incident(api, first.incident_id)["occurrence_index"] == 1, (
        "the first alarm of the term takes occurrence index 1"
    )

    X.set_clock(api, "2027-06-25T05:00:00Z")
    second = X.create_counted_incident(api, bundle, bundle.system_ids[1], "2027-06-25T04:00:00Z")
    assert X.get_incident(api, second.incident_id)["occurrence_index"] == 2, (
        "the second alarm of the same term takes occurrence index 2"
    )

    X.set_clock(api, "2027-07-05T00:00:00Z")
    X.run_nightly(api)
    A.assert_status(X.get_permit(api, bundle.permit_ids[0]), "RENEWAL_DUE")
    renewal = api.renew_permit(
        bundle.permit_ids[0],
        {"expected_alarm_permit_version": X.permit_version(api, bundle.permit_ids[0])},
        U.PERMIT_CLERK,
    )
    validate_success(renewal, 200)

    X.set_clock(api, "2027-08-16T05:00:00Z")
    third = X.create_reported_incident(
        api, bundle, bundle.system_ids[2], "2027-08-16T04:00:00Z", cause_code="EQUIPMENT_MALFUNCTION"
    )
    ruled = X.determine_counted(api, third.incident_id)
    assert ruled["counted_window_mode"] == "PERMIT_YEAR", (
        f"the governing schedule selects the permit-year variant, got {ruled['counted_window_mode']!r}"
    )
    assert ruled["occurrence_index"] == 1, (
        "the fresh term restarts the numbering at 1, got "
        f"{ruled['occurrence_index']}"
    )
    A.assert_money_cents(ruled["assessed_fee_cents"], 0, "assessed_fee_cents")

    summary = X.get_summary(api, bundle.site_id)
    assert summary["chargeable_count_rolling_365"] == 3, (
        "all three alarms sit inside the rolling year, got "
        f"{summary['chargeable_count_rolling_365']}"
    )
    assert summary["chargeable_count_permit_year"] == 1, (
        "only the post-renewal alarm sits inside the current term, got "
        f"{summary['chargeable_count_permit_year']}"
    )
    assert summary["chargeable_count_window"] == 1, (
        "the authoritative window follows the permit-year variant, got "
        f"{summary['chargeable_count_window']}"
    )

    fee_invoices = X.invoices_of_site(api, bundle.site_id, kind="FALSE_ALARM_FEE")
    assert fee_invoices == [], (
        "a zero subtotal under the allowance raises no invoice at all, got "
        f"{len(fee_invoices)}"
    )


def test_capped_and_uncapped_assessments_diverge_one_tier_apart(api):
    """Adjacent tiers straddle the per-incident cap, so the observed delta is the clip rather than the tier gap.

    PRD §3.5 states: "the cap is treated as applied only when the rounded amount
    is **strictly greater** than `per_incident_fee_cap_cents`, so an amount
    exactly equal to the cap passes through unchanged and is not flagged as
    capped; the amount is then clipped to the cap; and finally, if a suspension
    order for the premises in `EFFECTIVE` or `REINSTATEMENT_PENDING` covers the
    incident's occurrence instant within its closed interval from `effective_from`
    through `effective_through`, the flat `suspension_period_aggravation_cents`
    is added **after** the clip." PRD §3.8 states: "`admin_fee_cents` is then the
    subtotal times `admin_fee_pct`, rounded half up once on the already-rounded
    subtotal, and clamped upward to `admin_fee_min_cents` and downward to
    `admin_fee_max_cents`".

    Occurrence 5 prices at the 40000-cent tier times the COMMERCIAL multiplier of
    1.50, that is 60000, which is under the 100000-cent cap and passes through
    uncapped for an invoice of 60000 plus 3000 administrative fee, so 63000.
    Occurrence 6 prices at the 75000-cent tier times 1.50, that is 112500, which
    is strictly greater than the cap and is clipped to 100000 for an invoice of
    100000 plus the 5000-cent administrative ceiling, so 105000. The delta
    between the two assessments is therefore 40000 rather than the 52500 the tier
    table alone implies, and with no order in force over the occurrence the
    aggravation is zero, which is why the capped fee equals the cap exactly.

    Design: Corner/cross_cutting_complexity_layers/dual_variant_capped_and_uncapped_assessments_diverge_one_tier_apart
    """
    bundle = _commercial_premises(api, system_count=6, contact_count=3)
    counted = _counted_incidents(api, bundle, 5)
    sixth = X.create_reported_incident(api, bundle, bundle.system_ids[5], OCCURRENCES[5])

    capped = X.determine_counted(api, sixth.incident_id)

    uncapped = X.get_incident(api, counted[4].incident_id)
    assert uncapped["occurrence_index"] == 5, (
        f"the uncapped variant sits at occurrence 5, got {uncapped['occurrence_index']}"
    )
    A.assert_money_cents(uncapped["assessed_fee_cents"], 60000, "assessed_fee_cents")
    A.assert_fee_basis(
        uncapped["fee_basis"],
        tier_base_cents=40000,
        occupancy_multiplier=1.50,
        aggravation_cents=0,
        cap_applied=False,
    )
    A.assert_invoice_totals(
        X.invoice_for_incident(api, counted[4].incident_id),
        subtotal_cents=60000,
        admin_fee_cents=3000,
        assessed_cents=63000,
    )

    assert capped["occurrence_index"] == 6, (
        f"the capped variant sits at occurrence 6, got {capped['occurrence_index']}"
    )
    A.assert_money_cents(capped["assessed_fee_cents"], 100000, "assessed_fee_cents")
    A.assert_fee_basis(
        capped["fee_basis"],
        tier_base_cents=75000,
        occupancy_multiplier=1.50,
        aggravation_cents=0,
        cap_applied=True,
    )
    A.assert_invoice_totals(
        X.invoice_for_incident(api, sixth.incident_id),
        subtotal_cents=100000,
        admin_fee_cents=5000,
        assessed_cents=105000,
    )

    delta = capped["assessed_fee_cents"] - uncapped["assessed_fee_cents"]
    A.assert_money_cents(delta, 40000, "assessment delta")


def test_ecv_sufficiency_turns_on_distinct_contacts_not_call_count(api):
    """Two logs of two calls diverge on the distinct-contact count, and both verdicts freeze at submission.

    PRD §3.4 states: "`distinct_ecv_contact_count` is then the number of distinct
    contact identifiers surviving that filter, defaulting to 0 for an empty log."
    It also states: "Two consequences follow directly and are both intended: a log
    of two calls placed to the *same* contact yields a distinct count of 1 and is
    therefore insufficient for a two-call request even though two calls really
    were made, while a log of exactly two calls to *different* contacts yields 2,
    meets the inclusive threshold and is sufficient." On the consequence it
    states: "Validation requires the frozen `ecv_sufficient` to be true, else
    `ERR_ECV_REQUIREMENT_NOT_MET`". And on freezing: "Verification sufficiency is
    computed once, at submission, and frozen on the row."

    Both requests declare TWO_CALL_ECV and log exactly two attempts with eligible
    outcomes. The one that called a single responsible party twice records a
    distinct count of 1 and is insufficient, so it cannot be validated and is
    refused as call-verification deficient. The one that called two different
    parties records 2, meets the inclusive threshold, and validates normally.
    Removing the second party afterwards leaves that frozen verdict untouched.

    Design: Corner/cross_cutting_complexity_layers/dual_variant_ecv_sufficiency_turns_on_distinct_contacts_not_call_count
    """
    bundle = X.setup_program_baseline(api, contact_count=3, system_count=2)
    occurred_at = "2026-09-19T22:00:00Z"

    one_contact_id = X.submit_dispatch_request(
        api,
        bundle,
        bundle.system_ids[0],
        occurred_at,
        call_attempts=[
            F.call_attempt(bundle.contact_ids[0], X.plus_minutes(occurred_at, 1), "NO_ANSWER"),
            F.call_attempt(bundle.contact_ids[0], X.plus_minutes(occurred_at, 3), "VOICEMAIL"),
        ],
    )
    two_contact_id = X.submit_dispatch_request(
        api,
        bundle,
        bundle.system_ids[1],
        occurred_at,
        call_attempts=X.two_call_attempts(bundle, occurred_at),
    )

    insufficient = A.data_of(api.get_dispatch_request(one_contact_id, U.DISPATCH_SUPERVISOR))
    assert insufficient["distinct_ecv_contact_count"] == 1, (
        "two calls to one party resolve to a single distinct contact, got "
        f"{insufficient['distinct_ecv_contact_count']}"
    )
    assert insufficient["ecv_sufficient"] is False, (
        f"a distinct count of 1 is insufficient for a two-call request, got {insufficient['ecv_sufficient']!r}"
    )

    sufficient = A.data_of(api.get_dispatch_request(two_contact_id, U.DISPATCH_SUPERVISOR))
    assert sufficient["distinct_ecv_contact_count"] == 2, (
        "two calls to two parties resolve to two distinct contacts, got "
        f"{sufficient['distinct_ecv_contact_count']}"
    )
    assert sufficient["ecv_sufficient"] is True, (
        f"the threshold of 2 is inclusive, got {sufficient['ecv_sufficient']!r}"
    )

    refused_validation = api.validate_dispatch_request(one_contact_id, U.DISPATCH_SUPERVISOR)
    validate_error(refused_validation, E.ERR_ECV_REQUIREMENT_NOT_MET, expected_status=422)

    refusal = api.refuse_dispatch_request(
        one_contact_id, {"refusal_reason": "ECV_DEFICIENT"}, U.DISPATCH_SUPERVISOR
    )
    validate_success(refusal, 200)
    refused = get_success_data(refusal)
    A.assert_status(refused, "REFUSED")
    assert refused["refusal_reason"] == "ECV_DEFICIENT", (
        f"the coded reason must be stored, got {refused['refusal_reason']!r}"
    )

    validated = api.validate_dispatch_request(two_contact_id, U.DISPATCH_SUPERVISOR)
    validate_success(validated, 200)
    A.assert_status(get_success_data(validated), "VALIDATED")

    removal = api.delete_site_contact(bundle.contact_ids[1], U.PERMIT_CLERK)
    validate_success(removal, 200)

    frozen = A.data_of(api.get_dispatch_request(two_contact_id, U.DISPATCH_SUPERVISOR))
    assert frozen["ecv_sufficient"] is True, (
        "the verdict is frozen at submission and survives a later roster change, got "
        f"{frozen['ecv_sufficient']!r}"
    )
    assert frozen["distinct_ecv_contact_count"] == 2, (
        "the frozen distinct count must not be recomputed, got "
        f"{frozen['distinct_ecv_contact_count']}"
    )
