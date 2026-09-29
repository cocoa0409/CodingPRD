"""Occurrence numbering, the escalating false alarm fee, invoice assembly, the
delinquency ladder and the reinstatement requirement set — the money arithmetic
of the program checked against the literals the pinned schedule derives."""
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

# The clock convention of this file: permits are issued at the logical clock's
# startup instant, so the first permit's new-installation grace runs through
# 2026-08-31 and every chargeable occurrence below sits on or after 2026-09-15.
# Determinations are made with the clock parked at this instant.
DETERMINATION_CLOCK = "2026-09-20T01:00:00Z"

# Four occurrence instants in ascending order, one per alarm system.
OCCURRENCES = [
    "2026-09-15T03:09:00Z",
    "2026-09-16T04:00:00Z",
    "2026-09-17T04:00:00Z",
    "2026-09-18T04:00:00Z",
    "2026-09-19T04:00:00Z",
    "2026-09-19T05:00:00Z",
]

# A duress signal is submitted with no call log at all and no verification
# method, which is what arms the non-ECV surcharge.
DURESS_SIGNAL = {"alarm_type": "DURESS", "verification_method": "NONE", "call_attempts": []}


def _site(api, *, system_count, occupancy_class="COMMERCIAL", contact_count=3,
          schedule_overrides=None, clock=DETERMINATION_CLOCK, approve=True):
    """A premises with `system_count` permitted systems, all permitted at the
    clock's startup instant, with the clock then parked at `clock`."""
    return X.setup_program_baseline(
        api,
        clock=clock,
        schedule_overrides=schedule_overrides,
        site_overrides={"occupancy_class": occupancy_class},
        contact_count=contact_count,
        system_count=system_count,
        installed_at=C.CLOCK_STARTUP_UTC,
        approve=approve,
    )


def _counted(api, bundle, ordinal, **request_overrides):
    """Open and rule chargeable the incident for the system at `ordinal`."""
    incident = X.create_reported_incident(
        api, bundle, bundle.system_ids[ordinal], OCCURRENCES[ordinal], **request_overrides
    )
    return incident, X.determine_counted(api, incident.incident_id)


def _line(invoice, code):
    """The single line item of an invoice carrying `code`."""
    matches = [row for row in invoice["line_items"] if row["code"] == code]
    assert len(matches) == 1, f"expected exactly one {code} line, got {len(matches)}"
    return matches[0]


def test_occurrence_indices_are_contiguous_by_occurred_at(api):
    """Four chargeable occurrences at one premises take occurrence_index 1, 2, 3
    and 4 in order of their occurrence instants, and the premises counters agree.

    PRD §3.5: "In either case the incident's `occurrence_index` is the size of the set it belongs to — the incident is already counted at that point, so it counts itself — and `counted_window_mode` records which variant produced the number."
    PRD §3.5: "The set of `occurrence_index` values across those incidents is exactly the contiguous run from 1 to that count, with no gaps and no duplicates, assigned in order of occurrence instant ascending and, for ties, creation instant ascending."
    PRD §3.5: "The premises' own counters use the same two definitions but evaluated at the logical clock rather than at any one incident's instant: `chargeable_count_rolling_365` counts chargeable incidents in the 365 days up to now, `chargeable_count_permit_year` counts them from the current term start up to now, and `chargeable_count_window` is whichever of the two the governing `counting_window_mode` selects."
    PRD §3.5: "Both thresholds are inclusive: with the defaults, a window count of 4 puts the premises on probation and 3 does not, and a count of 6 proposes a suspension while 5 does not."

    Each incident sits on its own alarm system, because a dispatched request
    stays open on its system. Under the pinned ROLLING_365 window every earlier
    occurrence is inside the 365 days before the next one, so the indices run
    1, 2, 3, 4 and all three premises counters read 4. A window count of 4
    reaches the inclusive probation threshold of 4 but stays below the
    suspension threshold of 6, so no enforcement order is proposed. The premises
    has been assessed four permit issue invoices of 5500 plus the fee invoice of
    the third occurrence (15750) and of the fourth (47250), which is
    22000 + 15750 + 47250 = 85000 cents of lifetime assessment.

    Design: Corner/calculations/false_alarm_occurrence_index_assigns_contiguous_indices_by_occurred_at
    """
    bundle = _site(api, system_count=4)

    incidents = []
    for ordinal in range(3):
        incidents.append(_counted(api, bundle, ordinal))
    incidents.append(_counted(api, bundle, 3, **DURESS_SIGNAL))

    for ordinal, (_incident, determined) in enumerate(incidents):
        assert determined["occurrence_index"] == ordinal + 1, (
            f"occurrence {ordinal + 1} took index {determined['occurrence_index']}"
        )
        assert determined["counted_window_mode"] == "ROLLING_365", (
            f"counted_window_mode expected ROLLING_365, got {determined['counted_window_mode']!r}"
        )

    site = X.get_site(api, bundle.site_id)
    assert site["chargeable_count_rolling_365"] == 4, site["chargeable_count_rolling_365"]
    assert site["chargeable_count_permit_year"] == 4, site["chargeable_count_permit_year"]
    assert site["chargeable_count_window"] == 4, site["chargeable_count_window"]
    A.assert_status(site, "RESPONSE_PROBATION", field="response_status")
    A.assert_money_cents(site["lifetime_assessed_cents"], 85000, "lifetime_assessed_cents")

    assert X.orders_of_site(api, bundle.site_id) == [], (
        "a window count of 4 is below the suspension threshold of 6, so no order may be proposed"
    )


def test_index_three_applies_the_marginal_tier_and_occupancy_multiplier(api):
    """The third chargeable occurrence is priced at the marginal 10000-cent tier
    times the commercial multiplier, and its invoice adds a 5% administrative fee.

    PRD §3.5: "First, the marginal tier: the tier base is the `base_fee_cents` of the single `fee_tiers` entry whose `from_index` is at or below the index and whose `to_index` is either null or at or above the index — this is a marginal lookup, never a cumulative sum of lower tiers — and the tier base is then forced to zero whenever the index is at or below `free_alarm_allowance`."
    PRD §3.5: "Second, the three multiplicative factors: the occupancy multiplier is the schedule's `occupancy_multipliers` entry for the premises' `occupancy_class`; the surcharge factor is 1 plus `non_ecv_surcharge_pct` when the originating request's `verification_method` was `NONE` or `SINGLE_CALL`, and 1 otherwise; the unpermitted factor is `unpermitted_multiplier` when the request's frozen `system_permitted_at_occurrence` is false, and 1 otherwise."
    PRD §3.8: "`admin_fee_cents` is then the subtotal times `admin_fee_pct`, rounded half up once on the already-rounded subtotal, and clamped upward to `admin_fee_min_cents` and downward to `admin_fee_max_cents`; the clamp binds before the fee joins the assessment, so a 200-cent subtotal still carries the 500-cent floor and a 200000-cent subtotal carries the 5000-cent ceiling."
    PRD §3.8: "`issued_on` is the logical clock and `due_on` is `issued_on` plus `invoice_due_days` whole days."
    PRD §3.8: "It receives the next sequential `invoice_number` in issuance order, zero-padded in the form INV-000001."

    Index 3 selects the single tier entry spanning index 3, whose base is 10000
    cents — not the 0 + 0 + 10000 that a cumulative reading would give. Index 3
    is above the free allowance of 2, so the base is not forced to zero. The
    request used two-call verification, so the surcharge factor is 1, and the
    system was permitted at the occurrence, so the unpermitted factor is 1;
    10000 * 1.50 = 15000 exactly. The administrative fee is
    round_half_up(15000 * 0.05) = 750, inside the 500..5000 clamp, so the
    invoice assesses 15000 + 750 = 15750 and all of it is outstanding. Three
    permit issue invoices were numbered first, so this one is INV-000004; it is
    issued at the clock of 2026-09-20 and due 30 whole days later on 2026-10-20.
    The premises therefore owes 3 * 5500 + 15750 = 32250 cents.

    Design: Corner/calculations/escalating_false_alarm_fee_index_three_applies_marginal_tier_and_occupancy
    """
    bundle = _site(api, system_count=3)

    for ordinal in range(2):
        _incident, determined = _counted(api, bundle, ordinal)
        A.assert_money_cents(determined["assessed_fee_cents"], 0, "free allowance fee")

    incident, determined = _counted(api, bundle, 2)
    assert determined["occurrence_index"] == 3, determined["occurrence_index"]
    A.assert_money_cents(determined["assessed_fee_cents"], 15000, "assessed_fee_cents")
    A.assert_fee_basis(
        determined["fee_basis"],
        tier_base_cents=10000,
        occupancy_multiplier=1.50,
        non_ecv_surcharge_applied=False,
        unpermitted_multiplier_applied=False,
        cap_applied=False,
        aggravation_cents=0,
    )

    invoice = X.invoice_for_incident(api, incident.incident_id)
    assert invoice["kind"] == "FALSE_ALARM_FEE", invoice["kind"]
    A.assert_invoice_totals(
        invoice,
        subtotal_cents=15000,
        admin_fee_cents=750,
        assessed_cents=15750,
        outstanding_cents=15750,
    )
    assert invoice["invoice_number"] == "INV-000004", invoice["invoice_number"]
    assert X.date_part(str(invoice["issued_on"])) == "2026-09-20", invoice["issued_on"]
    assert X.date_part(str(invoice["due_on"])) == "2026-10-20", invoice["due_on"]

    site = X.get_site(api, bundle.site_id)
    A.assert_money_cents(site["outstanding_balance_cents"], 32250, "outstanding_balance_cents")
    A.assert_money_cents(site["lifetime_assessed_cents"], 32250, "lifetime_assessed_cents")


def test_duress_signal_arms_the_non_ecv_surcharge(api):
    """A duress signal with no call log is verification-sufficient yet still
    carries the non-ECV surcharge, pricing the fourth occurrence at 45000 cents.

    PRD §3.4: "`distinct_ecv_contact_count` is then the number of distinct contact identifiers surviving that filter, defaulting to 0 for an empty log."
    PRD §3.4: "From that count, `ecv_sufficient` is decided as follows: it is true whenever the `alarm_type` is `DURESS`, because a duress signal bypasses call verification entirely; otherwise it is true when the `verification_method` is `TWO_CALL_ECV` and `distinct_ecv_contact_count` is at least 2; otherwise it is true when the method is `AUDIO_VIDEO` and `audio_video_evidence` is true; otherwise it is true when the method is `GUARD_RESPONSE` and `guard_on_scene` is true; and in every remaining case it is false."
    PRD §3.5: "Second, the three multiplicative factors: the occupancy multiplier is the schedule's `occupancy_multipliers` entry for the premises' `occupancy_class`; the surcharge factor is 1 plus `non_ecv_surcharge_pct` when the originating request's `verification_method` was `NONE` or `SINGLE_CALL`, and 1 otherwise; the unpermitted factor is `unpermitted_multiplier` when the request's frozen `system_permitted_at_occurrence` is false, and 1 otherwise."
    PRD §3.5: "Third — and this is the only rounding in the whole computation — the tier base is multiplied by all three factors together and that single product is rounded half up to a whole cent."
    PRD §3.9: "Fifth, `renewal_block_active` becomes true exactly when `outstanding_balance_cents` is at or above `delinquent_balance_block_cents` — the comparison is inclusive, so a balance of exactly 50000 cents blocks renewal."

    The duress request carries an empty call log, so its distinct callable
    contact count is 0, and it is nevertheless sufficient because duress bypasses
    call verification. Its verification method of NONE is exactly what makes the
    surcharge factor 1.20. Index 4 selects the 25000-cent tier, the premises is
    commercial at 1.50, and the system was permitted at the occurrence so the
    unpermitted factor stays 1: 25000 * 1.50 * 1.20 = 45000 in one rounding step.
    The administrative fee is round_half_up(45000 * 0.05) = 2250, so the invoice
    assesses 47250. The premises then owes 4 * 5500 + 15750 + 47250 = 85000,
    which is at or above the 50000-cent blocking threshold.

    Design: Corner/calculations/escalating_false_alarm_fee_applies_the_non_ecv_surcharge_on_a_duress_signal
    """
    bundle = _site(api, system_count=4)

    for ordinal in range(3):
        _counted(api, bundle, ordinal)

    incident, determined = _counted(api, bundle, 3, **DURESS_SIGNAL)

    request = A.data_of(api.get_dispatch_request(incident.dispatch_request_id, U.DISPATCH_SUPERVISOR))
    assert request["ecv_sufficient"] is True, request["ecv_sufficient"]
    assert request["distinct_ecv_contact_count"] == 0, request["distinct_ecv_contact_count"]

    assert determined["occurrence_index"] == 4, determined["occurrence_index"]
    A.assert_money_cents(determined["assessed_fee_cents"], 45000, "assessed_fee_cents")
    A.assert_fee_basis(
        determined["fee_basis"],
        tier_base_cents=25000,
        occupancy_multiplier=1.50,
        non_ecv_surcharge_applied=True,
        unpermitted_multiplier_applied=False,
        cap_applied=False,
        aggravation_cents=0,
    )

    invoice = X.invoice_for_incident(api, incident.incident_id)
    A.assert_invoice_totals(
        invoice, subtotal_cents=45000, admin_fee_cents=2250, assessed_cents=47250
    )

    site = X.get_site(api, bundle.site_id)
    A.assert_money_cents(site["outstanding_balance_cents"], 85000, "outstanding_balance_cents")
    assert site["renewal_block_active"] is True, site["renewal_block_active"]


def test_exempt_rows_consume_no_occurrence_index(api):
    """An exempt determination consumes no occurrence index, so the next
    chargeable occurrence at the premises is numbered 1 rather than 2.

    PRD §3.5: "Only incidents in `COUNTED` or `APPEALED` are chargeable."
    PRD §3.5: "Rows in `REPORTED`, `UNDER_REVIEW`, `EXEMPT`, `EXEMPT_BY_APPEAL` or `VOIDED` never enter the set."
    PRD §3.5: "It sets `determination` to `EXEMPT`, stores the `exempt_cause_code`, stamps `determined_at` and `determined_by_user_id`, leaves `occurrence_index` null and `assessed_fee_cents` at 0, issues no invoice and changes no premises counter."
    PRD §3.5: "Both thresholds are inclusive: with the defaults, a window count of 4 puts the premises on probation and 3 does not, and a count of 6 proposes a suspension while 5 does not."

    The earlier severe-weather incident is ruled exempt, so it leaves
    occurrence_index null, assesses nothing and never enters the chargeable set.
    The later incident is therefore the only member of its window and takes index
    1, and both premises counters read 1. One is below the inclusive probation
    threshold of 4, so the posture stays active. Index 1 is at or below the free
    allowance of 2, so the tier base is forced to zero and no false alarm fee
    invoice exists; the only money assessed against the premises is its two
    permit issue invoices of 5500 each, which is 11000 cents.

    Design: Corner/calculations/false_alarm_occurrence_index_skips_exempt_rows_when_numbering
    """
    bundle = _site(api, system_count=2)

    weather = X.create_reported_incident(
        api, bundle, bundle.system_ids[0], OCCURRENCES[0], cause_code="SEVERE_WEATHER"
    )
    exempted = X.determine_exempt(api, weather.incident_id, "SEVERE_WEATHER")
    A.assert_status(exempted, "EXEMPT")
    assert exempted["occurrence_index"] is None, exempted["occurrence_index"]
    A.assert_money_cents(exempted["assessed_fee_cents"], 0, "exempt assessed_fee_cents")

    _incident, determined = _counted(api, bundle, 1)
    assert determined["occurrence_index"] == 1, (
        f"the exempt row must not consume index 1, but the counted row took "
        f"{determined['occurrence_index']}"
    )
    A.assert_money_cents(determined["assessed_fee_cents"], 0, "assessed_fee_cents")

    site = X.get_site(api, bundle.site_id)
    assert site["chargeable_count_rolling_365"] == 1, site["chargeable_count_rolling_365"]
    assert site["chargeable_count_window"] == 1, site["chargeable_count_window"]
    A.assert_status(site, "RESPONSE_ACTIVE", field="response_status")
    A.assert_money_cents(site["lifetime_assessed_cents"], 11000, "lifetime_assessed_cents")

    fee_invoices = X.invoices_of_site(api, bundle.site_id, kind="FALSE_ALARM_FEE")
    assert fee_invoices == [], "a fee inside the free allowance must raise no invoice at all"


def test_counted_window_mode_follows_the_pinned_schedule(api):
    """counted_window_mode is taken from the schedule pinned to the premises, not
    from whichever schedule happens to be active when the ruling is made.

    PRD §2.9: "A premises is **pinned** to a schedule the first time any of its systems is permitted: at that moment `governing_fee_schedule_id` on the `AlarmSite` is set to the currently `ACTIVE` schedule and becomes immutable, and it stays null until then."
    PRD §2.9: "Every subsequent assessment for that premises — occurrence counting, fee tiers, occupancy multipliers, caps, thresholds, appeal windows, permit terms, invoice terms, delinquency rules — reads the pinned schedule and not whatever schedule happens to be `ACTIVE` later."
    PRD §3.5: "In either case the incident's `occurrence_index` is the size of the set it belongs to — the incident is already counted at that point, so it counts itself — and `counted_window_mode` records which variant produced the number."
    PRD §3.5: "The premises' own counters use the same two definitions but evaluated at the logical clock rather than at any one incident's instant: `chargeable_count_rolling_365` counts chargeable incidents in the 365 days up to now, `chargeable_count_permit_year` counts them from the current term start up to now, and `chargeable_count_window` is whichever of the two the governing `counting_window_mode` selects."

    The premises is pinned at its first permit issuance to a schedule counting
    under the permit-year variant. A second schedule counting under the rolling
    variant is then activated, superseding the first, but the ruling still reads
    the pinned row: the incident stamps counted_window_mode PERMIT_YEAR, and the
    premises' authoritative window count follows chargeable_count_permit_year.
    The occurrence is the first of its term, so index 1 is at or below the free
    allowance of 2, the tier base is forced to zero and no fee invoice is raised.

    Design: Corner/calculations/false_alarm_occurrence_index_variant_selection_follows_the_pinned_schedule
    """
    bundle = _site(
        api,
        system_count=1,
        occupancy_class="RESIDENTIAL",
        schedule_overrides={"counting_window_mode": "PERMIT_YEAR"},
    )

    site = X.get_site(api, bundle.site_id)
    assert site["governing_fee_schedule_id"] == bundle.schedule_id, (
        f"the premises must stay pinned to {bundle.schedule_id}, "
        f"got {site['governing_fee_schedule_id']!r}"
    )

    # A newer ordinance takes effect program-wide; the pinned premises is untouched.
    later_schedule_id = X.create_active_fee_schedule(api, counting_window_mode="ROLLING_365")
    assert later_schedule_id != bundle.schedule_id

    _incident, determined = _counted(api, bundle, 0)
    assert determined["counted_window_mode"] == "PERMIT_YEAR", (
        f"counted_window_mode must come from the pinned schedule, "
        f"got {determined['counted_window_mode']!r}"
    )
    assert determined["occurrence_index"] == 1, determined["occurrence_index"]
    A.assert_money_cents(determined["assessed_fee_cents"], 0, "assessed_fee_cents")

    site = X.get_site(api, bundle.site_id)
    assert site["governing_fee_schedule_id"] == bundle.schedule_id, site["governing_fee_schedule_id"]
    assert site["chargeable_count_permit_year"] == 1, site["chargeable_count_permit_year"]
    assert site["chargeable_count_window"] == 1, site["chargeable_count_window"]

    assert X.invoices_of_site(api, bundle.site_id, kind="FALSE_ALARM_FEE") == [], (
        "index 1 is inside the free allowance, so no fee invoice may be issued"
    )


def test_fee_rounds_once_at_the_end_not_per_factor(api):
    """The tier base is multiplied by every factor before a single rounding, so a
    3333-cent base at a school with the surcharge armed prices at 5000, not 4999.

    PRD §2.7: "Where a base amount is multiplied by several factors — the false alarm fee is the canonical case — the factors are multiplied together into a single product and that product is rounded once."
    PRD §2.7: "Rounding each factor's contribution separately is wrong and will produce different money."
    PRD §3.5: "Third — and this is the only rounding in the whole computation — the tier base is multiplied by all three factors together and that single product is rounded half up to a whole cent."
    PRD §3.8: "`admin_fee_cents` is then the subtotal times `admin_fee_pct`, rounded half up once on the already-rounded subtotal, and clamped upward to `admin_fee_min_cents` and downward to `admin_fee_max_cents`; the clamp binds before the fee joins the assessment, so a 200-cent subtotal still carries the 500-cent floor and a 200000-cent subtotal carries the 5000-cent ceiling."

    The schedule prices every index from a 3333-cent base with a free allowance
    of zero, the premises is a school at 1.25, and the duress request's
    verification method of NONE arms the 0.20 surcharge for a factor of 1.20.
    The single product is 3333 * 1.25 * 1.20 = 4999.5, which rounds half up to
    5000. Rounding after the occupancy multiplier instead would give
    round_half_up(4166.25) = 4166 and then 4166 * 1.20 = 4999.2 -> 4999, one cent
    short. The administrative fee is round_half_up(5000 * 0.05) = 250, clamped up
    to the 500-cent floor, so the invoice assesses 5000 + 500 = 5500.

    Design: Corner/calculations/escalating_false_alarm_fee_rounds_once_at_the_end_not_per_factor
    """
    bundle = _site(
        api,
        system_count=1,
        occupancy_class="SCHOOL",
        schedule_overrides={
            "free_alarm_allowance": 0,
            "fee_tiers": [{"from_index": 1, "to_index": None, "base_fee_cents": 3333}],
        },
    )

    incident, determined = _counted(api, bundle, 0, **DURESS_SIGNAL)
    assert determined["occurrence_index"] == 1, determined["occurrence_index"]
    A.assert_money_cents(determined["assessed_fee_cents"], 5000, "assessed_fee_cents")
    A.assert_fee_basis(
        determined["fee_basis"],
        tier_base_cents=3333,
        occupancy_multiplier=1.25,
        non_ecv_surcharge_applied=True,
        unpermitted_multiplier_applied=False,
        cap_applied=False,
        aggravation_cents=0,
    )

    invoice = X.invoice_for_incident(api, incident.incident_id)
    A.assert_invoice_totals(
        invoice, subtotal_cents=5000, admin_fee_cents=500, assessed_cents=5500
    )


def test_raw_equal_to_the_cap_is_not_reported_as_capped(api):
    """An amount landing exactly on the per-incident cap passes through unchanged
    and is not flagged as capped, so its invoice line is not overridden.

    PRD §3.5: "Fourth, the cap and the aggravation: the cap is treated as applied only when the rounded amount is **strictly greater** than `per_incident_fee_cap_cents`, so an amount exactly equal to the cap passes through unchanged and is not flagged as capped; the amount is then clipped to the cap; and finally, if a suspension order for the premises in `EFFECTIVE` or `REINSTATEMENT_PENDING` covers the incident's occurrence instant within its closed interval from `effective_from` through `effective_through`, the flat `suspension_period_aggravation_cents` is added **after** the clip."
    PRD §3.8: "A `FALSE_ALARM_FEE` invoice carries a first line coded FALSE_ALARM_BASE whose `unit_amount_cents` is the incident's tier base, `quantity` 1, and `multiplier` the product of the occupancy multiplier, the surcharge factor and the unpermitted factor — and when the incident's `fee_basis` records `cap_applied`, that line's `extended_cents` is overridden to `per_incident_fee_cap_cents`; it carries a second line coded SUSPENSION_PERIOD_AGGRAVATION at the aggravation amount with `multiplier` 1.00, present only when the aggravation is above zero."
    PRD §3.8: "`admin_fee_cents` is then the subtotal times `admin_fee_pct`, rounded half up once on the already-rounded subtotal, and clamped upward to `admin_fee_min_cents` and downward to `admin_fee_max_cents`; the clamp binds before the fee joins the assessment, so a 200-cent subtotal still carries the 500-cent floor and a 200000-cent subtotal carries the 5000-cent ceiling."

    The schedule prices index 1 at a 100000-cent base with a free allowance of
    zero and a per-incident cap of exactly 100000. The premises is residential at
    1.00, the request used two-call verification and the system was permitted, so
    the rounded amount is 100000 * 1.00 = 100000 — equal to the cap, never
    strictly above it, so cap_applied is false, no aggravation applies, and the
    base line's extended amount is its own 100000 rather than an override. The
    administrative fee is round_half_up(100000 * 0.05) = 5000, exactly the
    5000-cent ceiling, so the downward clamp is a no-op and the invoice assesses
    100000 + 5000 = 105000.

    Design: Corner/calculations/escalating_false_alarm_fee_raw_equal_to_the_cap_is_not_reported_as_capped
    """
    bundle = _site(
        api,
        system_count=1,
        occupancy_class="RESIDENTIAL",
        schedule_overrides={
            "free_alarm_allowance": 0,
            "fee_tiers": [{"from_index": 1, "to_index": None, "base_fee_cents": 100000}],
            "per_incident_fee_cap_cents": 100000,
        },
    )

    incident, determined = _counted(api, bundle, 0)
    A.assert_money_cents(determined["assessed_fee_cents"], 100000, "assessed_fee_cents")
    A.assert_fee_basis(
        determined["fee_basis"],
        tier_base_cents=100000,
        occupancy_multiplier=1.00,
        non_ecv_surcharge_applied=False,
        unpermitted_multiplier_applied=False,
        cap_applied=False,
        aggravation_cents=0,
    )

    invoice = X.invoice_for_incident(api, incident.incident_id)
    base_line = _line(invoice, "FALSE_ALARM_BASE")
    A.assert_money_cents(base_line["extended_cents"], 100000, "FALSE_ALARM_BASE extended_cents")
    A.assert_invoice_totals(
        invoice, subtotal_cents=100000, admin_fee_cents=5000, assessed_cents=105000
    )


def test_raw_above_the_cap_clips_and_overrides_the_invoice_line(api):
    """An amount strictly above the per-incident cap is clipped, is flagged as
    capped, and drags the invoice's base line down to the cap with it.

    PRD §3.5: "Fourth, the cap and the aggravation: the cap is treated as applied only when the rounded amount is **strictly greater** than `per_incident_fee_cap_cents`, so an amount exactly equal to the cap passes through unchanged and is not flagged as capped; the amount is then clipped to the cap; and finally, if a suspension order for the premises in `EFFECTIVE` or `REINSTATEMENT_PENDING` covers the incident's occurrence instant within its closed interval from `effective_from` through `effective_through`, the flat `suspension_period_aggravation_cents` is added **after** the clip."
    PRD §3.8: "A `FALSE_ALARM_FEE` invoice carries a first line coded FALSE_ALARM_BASE whose `unit_amount_cents` is the incident's tier base, `quantity` 1, and `multiplier` the product of the occupancy multiplier, the surcharge factor and the unpermitted factor — and when the incident's `fee_basis` records `cap_applied`, that line's `extended_cents` is overridden to `per_incident_fee_cap_cents`; it carries a second line coded SUSPENSION_PERIOD_AGGRAVATION at the aggravation amount with `multiplier` 1.00, present only when the aggravation is above zero."
    PRD §3.9: "Third, `lifetime_assessed_cents` is the sum of `assessed_cents` over every invoice of the premises whose `payment_status` is not `VOIDED` — so a written-off invoice still counts toward lifetime assessment even though it has left the outstanding balance."

    The same 100000-cent base on a commercial premises multiplies to
    100000 * 1.50 = 150000, which is strictly above the 100000-cent cap, so
    cap_applied is true and the assessed fee clips to 100000. The base line's
    extended amount is overridden to the cap rather than carrying the pre-clip
    150000, so the subtotal is 100000, the administrative fee is
    round_half_up(100000 * 0.05) = 5000 and the invoice assesses 105000. The
    premises' lifetime assessment is that 105000 plus its single permit issue
    invoice of 5500, which is 110500 — nothing derived from the pre-clip 150000.

    Design: Corner/calculations/escalating_false_alarm_fee_clips_above_the_cap_and_overrides_the_invoice_line
    """
    bundle = _site(
        api,
        system_count=1,
        occupancy_class="COMMERCIAL",
        schedule_overrides={
            "free_alarm_allowance": 0,
            "fee_tiers": [{"from_index": 1, "to_index": None, "base_fee_cents": 100000}],
            "per_incident_fee_cap_cents": 100000,
        },
    )

    incident, determined = _counted(api, bundle, 0)
    assert determined["occurrence_index"] == 1, determined["occurrence_index"]
    A.assert_money_cents(determined["assessed_fee_cents"], 100000, "assessed_fee_cents")
    A.assert_fee_basis(
        determined["fee_basis"],
        tier_base_cents=100000,
        occupancy_multiplier=1.50,
        non_ecv_surcharge_applied=False,
        unpermitted_multiplier_applied=False,
        cap_applied=True,
        aggravation_cents=0,
    )

    invoice = X.invoice_for_incident(api, incident.incident_id)
    base_line = _line(invoice, "FALSE_ALARM_BASE")
    A.assert_money_cents(base_line["extended_cents"], 100000, "FALSE_ALARM_BASE extended_cents")
    A.assert_invoice_totals(
        invoice, subtotal_cents=100000, admin_fee_cents=5000, assessed_cents=105000
    )

    site = X.get_site(api, bundle.site_id)
    A.assert_money_cents(site["lifetime_assessed_cents"], 110500, "lifetime_assessed_cents")


def test_admin_fee_clamps_up_to_the_minimum_on_a_permit_fee(api):
    """A permit issue invoice whose percentage administrative fee falls below the
    floor is charged the floor, and the floor binds before the assessment is summed.

    PRD §3.8: "A `PERMIT_ISSUE_FEE` invoice carries one PERMIT_ISSUE line at `permit_issue_fee_cents`."
    PRD §3.8: "The rounding order is pinned and is not a matter of taste: each line's `extended_cents` is `unit_amount_cents` times `quantity` times `multiplier`, rounded half up to a whole cent, and only then are the lines summed into `subtotal_cents`."
    PRD §3.8: "`admin_fee_cents` is then the subtotal times `admin_fee_pct`, rounded half up once on the already-rounded subtotal, and clamped upward to `admin_fee_min_cents` and downward to `admin_fee_max_cents`; the clamp binds before the fee joins the assessment, so a 200-cent subtotal still carries the 500-cent floor and a 200000-cent subtotal carries the 5000-cent ceiling."
    PRD §3.8: "`late_penalty_cents` is 0 at issuance."
    PRD §3.8: "`issued_on` is the logical clock and `due_on` is `issued_on` plus `invoice_due_days` whole days."
    PRD §3.9: "Fifth, `renewal_block_active` becomes true exactly when `outstanding_balance_cents` is at or above `delinquent_balance_block_cents` — the comparison is inclusive, so a balance of exactly 50000 cents blocks renewal."

    The single permit issue line is 5000 * 1 * 1.00 = 5000, so the subtotal is
    5000 and round_half_up(5000 * 0.05) = 250. That is below the 500-cent floor,
    so the fee is raised to 500 before it joins the assessment and the invoice
    assesses 5000 + 500 + 0 = 5500; clamping after summing would have reported
    5250. It is the program's first invoice, so it is numbered INV-000001, issued
    at the clock of 2026-08-01 and due 30 whole days later on 2026-08-31. The
    premises now owes 5500, strictly below the 50000-cent blocking threshold, so
    renewal is not blocked.

    Design: Corner/calculations/invoice_assembly_clamps_the_admin_fee_up_to_the_minimum_on_a_permit_fee
    """
    bundle = _site(
        api, system_count=1, clock=C.CLOCK_STARTUP_UTC, approve=False
    )

    issued = A.data_of(
        api.approve_registration(bundle.system_ids[0], U.PERMIT_CLERK), expected_status=201
    )
    permit_id = issued["id"]

    invoice = A.single(
        api.list_penalty_invoices(
            U.BILLING_CLERK, {"alarm_permit_id": permit_id, "kind": "PERMIT_ISSUE_FEE"}
        )
    )
    issue_line = _line(invoice, "PERMIT_ISSUE")
    A.assert_money_cents(issue_line["unit_amount_cents"], 5000, "PERMIT_ISSUE unit_amount_cents")
    assert issue_line["quantity"] == 1, issue_line["quantity"]
    assert float(issue_line["multiplier"]) == 1.00, issue_line["multiplier"]
    A.assert_money_cents(issue_line["extended_cents"], 5000, "PERMIT_ISSUE extended_cents")

    A.assert_invoice_totals(
        invoice,
        subtotal_cents=5000,
        admin_fee_cents=500,
        assessed_cents=5500,
        outstanding_cents=5500,
    )
    A.assert_money_cents(invoice["late_penalty_cents"], 0, "late_penalty_cents")
    assert invoice["invoice_number"] == "INV-000001", invoice["invoice_number"]
    assert X.date_part(str(invoice["issued_on"])) == "2026-08-01", invoice["issued_on"]
    assert X.date_part(str(invoice["due_on"])) == "2026-08-31", invoice["due_on"]

    site = X.get_site(api, bundle.site_id)
    A.assert_money_cents(site["outstanding_balance_cents"], 5500, "outstanding_balance_cents")
    assert site["renewal_block_active"] is False, site["renewal_block_active"]


def test_admin_fee_clamps_down_to_the_maximum_on_a_large_fee(api):
    """A 200000-cent subtotal attracts the administrative ceiling rather than the
    full 5% of the subtotal.

    PRD §3.8: "`admin_fee_cents` is then the subtotal times `admin_fee_pct`, rounded half up once on the already-rounded subtotal, and clamped upward to `admin_fee_min_cents` and downward to `admin_fee_max_cents`; the clamp binds before the fee joins the assessment, so a 200-cent subtotal still carries the 500-cent floor and a 200000-cent subtotal carries the 5000-cent ceiling."
    PRD §3.8: "`assessed_cents` is `subtotal_cents` plus `admin_fee_cents` plus `late_penalty_cents`; `paid_cents` and `adjusted_cents` start at 0; `outstanding_cents` is `assessed_cents` minus `paid_cents` minus `adjusted_cents`, floored at zero and never negative."
    PRD §3.5: "Fourth, the cap and the aggravation: the cap is treated as applied only when the rounded amount is **strictly greater** than `per_incident_fee_cap_cents`, so an amount exactly equal to the cap passes through unchanged and is not flagged as capped; the amount is then clipped to the cap; and finally, if a suspension order for the premises in `EFFECTIVE` or `REINSTATEMENT_PENDING` covers the incident's occurrence instant within its closed interval from `effective_from` through `effective_through`, the flat `suspension_period_aggravation_cents` is added **after** the clip."
    PRD §3.9: "Fifth, `renewal_block_active` becomes true exactly when `outstanding_balance_cents` is at or above `delinquent_balance_block_cents` — the comparison is inclusive, so a balance of exactly 50000 cents blocks renewal."

    The schedule prices index 1 at a 200000-cent base with a free allowance of
    zero and lifts the per-incident cap to 500000, so the cap cannot interfere:
    200000 * 1.00 is 200000, not strictly above 500000, so cap_applied is false.
    The percentage administrative fee would be round_half_up(200000 * 0.05) =
    10000, but the 5000-cent ceiling clips it, so the invoice assesses
    200000 + 5000 = 205000 and not 210000, all of it outstanding. With the
    premises' 5500-cent permit issue invoice that is 210500 owed, at or above the
    50000-cent blocking threshold.

    Design: Corner/calculations/invoice_assembly_clamps_the_admin_fee_down_to_the_maximum_on_a_large_fee
    """
    bundle = _site(
        api,
        system_count=1,
        occupancy_class="RESIDENTIAL",
        schedule_overrides={
            "free_alarm_allowance": 0,
            "fee_tiers": [{"from_index": 1, "to_index": None, "base_fee_cents": 200000}],
            "per_incident_fee_cap_cents": 500000,
        },
    )

    incident, determined = _counted(api, bundle, 0)
    A.assert_money_cents(determined["assessed_fee_cents"], 200000, "assessed_fee_cents")
    A.assert_fee_basis(determined["fee_basis"], cap_applied=False)

    invoice = X.invoice_for_incident(api, incident.incident_id)
    A.assert_invoice_totals(
        invoice,
        subtotal_cents=200000,
        admin_fee_cents=5000,
        assessed_cents=205000,
        outstanding_cents=205000,
    )

    site = X.get_site(api, bundle.site_id)
    A.assert_money_cents(site["outstanding_balance_cents"], 210500, "outstanding_balance_cents")
    assert site["renewal_block_active"] is True, site["renewal_block_active"]


def test_invoice_numbers_run_sequentially_in_issuance_order(api):
    """Invoice numbers are one global sequence stamped in issuance order, so four
    permit invoices are numbered before the first false alarm fee invoice.

    PRD §3.8: "It receives the next sequential `invoice_number` in issuance order, zero-padded in the form INV-000001."
    PRD §3.8: "The one case that produces no row at all is a false alarm inside the free allowance with no aggravation: a zero subtotal means no invoice and therefore no administrative fee either."
    PRD §3.9: "Second, `outstanding_balance_cents` is the sum of `outstanding_cents` over the premises' invoices whose `payment_status` is `UNPAID` or `PARTIALLY_PAID` and whose `collections_stage` is not `WRITTEN_OFF`."

    Four registrations are approved first, so their permit issue invoices take
    INV-000001 through INV-000004 in issuance order. Occurrences 1 and 2 are
    inside the free allowance of 2 and raise no invoice at all. Occurrence 3 is
    priced at 10000 * 1.50 = 15000 plus round_half_up(750) for 15750 and takes
    INV-000005; occurrence 4 is a duress signal priced at
    25000 * 1.50 * 1.20 = 45000 plus round_half_up(2250) for 47250 and takes
    INV-000006. Six rows exist for the premises and their assessments sum to
    4 * 5500 + 15750 + 47250 = 85000, which is exactly what the premises owes.

    Design: Corner/calculations/invoice_assembly_numbers_invoices_sequentially_in_issuance_order
    """
    bundle = _site(api, system_count=4)

    for ordinal in range(3):
        _counted(api, bundle, ordinal)
    duress_incident, _determined = _counted(api, bundle, 3, **DURESS_SIGNAL)

    rows = A.assert_total_count(
        api.list_penalty_invoices(
            U.BILLING_CLERK, {"alarm_site_id": bundle.site_id, "page": 1, "per_page": 25}
        ),
        6,
    )
    by_number = {row["invoice_number"]: row for row in rows}
    assert sorted(by_number) == [
        "INV-000001",
        "INV-000002",
        "INV-000003",
        "INV-000004",
        "INV-000005",
        "INV-000006",
    ], sorted(by_number)

    for number in ("INV-000001", "INV-000002", "INV-000003", "INV-000004"):
        permit_invoice = by_number[number]
        assert permit_invoice["kind"] == "PERMIT_ISSUE_FEE", (
            f"{number} expected to be a permit issue invoice, got {permit_invoice['kind']!r}"
        )
        A.assert_money_cents(permit_invoice["assessed_cents"], 5500, f"{number} assessed_cents")

    fifth = by_number["INV-000005"]
    assert fifth["kind"] == "FALSE_ALARM_FEE", fifth["kind"]
    A.assert_money_cents(fifth["assessed_cents"], 15750, "INV-000005 assessed_cents")

    sixth = by_number["INV-000006"]
    assert sixth["kind"] == "FALSE_ALARM_FEE", sixth["kind"]
    assert sixth["false_alarm_incident_id"] == duress_incident.incident_id, (
        "the sixth invoice must belong to the fourth occurrence"
    )
    A.assert_money_cents(sixth["assessed_cents"], 47250, "INV-000006 assessed_cents")

    total_assessed = sum(row["assessed_cents"] for row in rows)
    A.assert_money_cents(total_assessed, 85000, "sum of assessed_cents")
    site = X.get_site(api, bundle.site_id)
    A.assert_money_cents(site["outstanding_balance_cents"], 85000, "outstanding_balance_cents")


def _dunned_unpermitted_penalty(api, penalty_cents):
    """Revoke a permit, then dun the resulting penalty invoice to final notice
    with the clock parked exactly `delinquency_days` past its due date."""
    bundle = _site(
        api,
        system_count=1,
        contact_count=2,
        clock=C.CLOCK_STARTUP_UTC,
        schedule_overrides={
            "unpermitted_operation_penalty_cents": penalty_cents,
            "permit_issue_fee_cents": 0,
            "admin_fee_pct": 0,
            "admin_fee_min_cents": 0,
        },
    )
    validate_success(
        api.revoke_permit(
            bundle.permit_ids[0],
            {"revocation_reason": "Permit revoked for cause: repeated unverified signals."},
            U.PROGRAM_ADMIN,
        ),
        200,
    )
    invoice_id = X.invoices_of_site(
        api, bundle.site_id, kind="UNPERMITTED_OPERATION_PENALTY"
    )[0]["id"]

    # Due 2026-08-31; one whole day late raises the one-time late penalty and
    # thirty whole days late carries the invoice on to final notice.
    X.set_clock(api, "2026-09-01T00:00:00Z")
    X.run_nightly(api)
    X.set_clock(api, "2026-09-30T00:00:00Z")
    X.run_nightly(api)
    X.set_clock(api, "2026-11-29T00:00:00Z")
    return bundle, invoice_id


def test_collections_tier_is_priced_after_the_late_penalty(api):
    """The collections charge is keyed on the interim total that already contains
    the late penalty, so a 24000-cent principal is referred at 28512 cents.

    PRD §3.8: "Step two: `late_penalty_cents` is that principal times `late_penalty_pct`, rounded half up, and is added into `assessed_cents` — once per invoice, never twice."
    PRD §3.8: "Step three: an interim total is recomputed as `assessed_cents` minus `paid_cents` minus `adjusted_cents`, **after** step two."
    PRD §3.8: "Step four: the collections administrative charge is a flat 2000 cents when the interim total is at or below 25000 cents, the interim total times 0.08 rounded half up when it is above 25000 and at or below 100000, and a flat 10000 cents when it is above 100000."
    PRD §3.8: "Step five: `referral_total_cents` is the interim total plus that charge."
    PRD §3.8: "The order matters concretely — a 24000-cent principal becomes 26400 at step three, which lands in the middle tier for a 2112-cent charge and a 28512-cent referral total, whereas pricing the tier off the pre-penalty 24000 would have yielded the 2000-cent flat charge and 26400."
    PRD §3.8: "And `referral_total_cents` is what the agency is handed, not what the premises owes the city: it does not feed `outstanding_cents`, so the premises' `outstanding_balance_cents` is untouched by the collections charge."
    PRD §3.8: "`days_delinquent` is the whole days between `due_on` and the logical clock, floored at zero."

    Revoking the permit raises a 24000-cent penalty invoice with the
    administrative fee configured away, due 2026-08-31. The first nightly run
    adds round_half_up(24000 * 0.10) = 2400 once, taking the assessment to 26400,
    and the second carries the invoice to final notice. At 2026-11-29 the invoice
    is exactly 90 whole days delinquent, meeting the inclusive 90-day gate, and
    its 26400 outstanding is at or above the 25000-cent referral threshold. The
    interim total of 26400 is above 25000 and at or below 100000, so the charge is
    round_half_up(26400 * 0.08) = 2112 and the referral total is 28512 — not the
    26400 that pricing the tier off the pre-penalty principal would give.

    Design: Corner/calculations/delinquency_escalation_prices_the_collections_tier_after_the_late_penalty
    """
    bundle, invoice_id = _dunned_unpermitted_penalty(api, 24000)

    before = X.get_invoice(api, invoice_id)
    A.assert_money_cents(before["late_penalty_cents"], 2400, "late_penalty_cents")
    A.assert_invoice_totals(
        before, assessed_cents=26400, outstanding_cents=26400, collections_stage="FINAL_NOTICE"
    )
    assert before["days_delinquent"] == 90, before["days_delinquent"]

    referred = A.data_of(
        api.refer_invoice_to_collections(
            invoice_id, {"referral_agency": "Trinity Municipal Recovery Services"}, U.BILLING_CLERK
        )
    )
    A.assert_status(referred, "REFERRED", field="collections_stage")
    assert referred["referral_agency"] == "Trinity Municipal Recovery Services", (
        referred["referral_agency"]
    )
    assert X.date_part(str(referred["referred_on"])) == "2026-11-29", referred["referred_on"]
    A.assert_money_cents(referred["referral_total_cents"], 28512, "referral_total_cents")
    A.assert_money_cents(referred["outstanding_cents"], 26400, "outstanding_cents")

    site = X.get_site(api, bundle.site_id)
    A.assert_money_cents(site["outstanding_balance_cents"], 26400, "outstanding_balance_cents")


def test_interim_total_at_the_low_bound_takes_the_flat_collections_fee(api):
    """An interim total landing exactly on 25000 sits with the lower comparison and
    takes the flat 2000-cent collections charge.

    PRD §3.8: "Step two: `late_penalty_cents` is that principal times `late_penalty_pct`, rounded half up, and is added into `assessed_cents` — once per invoice, never twice."
    PRD §3.8: "Step four: the collections administrative charge is a flat 2000 cents when the interim total is at or below 25000 cents, the interim total times 0.08 rounded half up when it is above 25000 and at or below 100000, and a flat 10000 cents when it is above 100000."
    PRD §3.8: "Both tier bounds sit with the lower comparison: exactly 25000 takes the 2000-cent flat charge, 25001 takes the 0.08 rate, exactly 100000 still takes the 0.08 rate for 8000 cents, and 100001 takes the 10000-cent flat charge."
    PRD §3.8: "Every criterion must hold together: `collections_stage` must be `FINAL_NOTICE`, `days_delinquent` at or above `delinquency_days`, and `outstanding_cents` at or above `collections_referral_threshold_cents`, else `ERR_REFERRAL_CRITERIA_NOT_MET`; the linked incident must not be `APPEALED`, else `ERR_INVOICE_UNDER_APPEAL`; and a written-off invoice may not be referred, else `ERR_INVOICE_WRITTEN_OFF`."

    A 22727-cent principal attracts a late penalty of
    round_half_up(22727 * 0.10) = round_half_up(2272.7) = 2273, so the assessment
    becomes exactly 25000 and the interim total is exactly 25000. That is at or
    below the 25000-cent bound, so the charge is the flat 2000 and the referral
    total is 25000 + 2000 = 27000. The same 25000 outstanding also meets the
    inclusive 25000-cent referral threshold, so the referral is admitted at both
    edges at once.

    Design: Corner/calculations/delinquency_escalation_interim_total_exactly_at_the_low_bound_takes_the_flat_fee
    """
    _bundle, invoice_id = _dunned_unpermitted_penalty(api, 22727)

    before = X.get_invoice(api, invoice_id)
    A.assert_money_cents(before["late_penalty_cents"], 2273, "late_penalty_cents")
    A.assert_invoice_totals(
        before, assessed_cents=25000, outstanding_cents=25000, collections_stage="FINAL_NOTICE"
    )

    referred = A.data_of(
        api.refer_invoice_to_collections(
            invoice_id, {"referral_agency": "Trinity Municipal Recovery Services"}, U.BILLING_CLERK
        )
    )
    A.assert_status(referred, "REFERRED", field="collections_stage")
    A.assert_money_cents(referred["referral_total_cents"], 27000, "referral_total_cents")
    A.assert_money_cents(referred["outstanding_cents"], 25000, "outstanding_cents")


def test_first_suspension_reinstatement_set_prices_at_the_base_fee(api):
    """A first suspension freezes its whole reinstatement requirement set off a
    prior lifted count of zero: 60000 cents, 90 probation days, sequence 1, 2 contacts.

    PRD §3.5: "And when `chargeable_count_window` reaches or exceeds `suspension_threshold_count`, an enforcement order is auto-proposed for the premises: a suspension order in `PROPOSED` with `basis` of `EXCESSIVE_FALSE_ALARMS`, its `triggering_incident_id` set to this incident, `effective_from` at the logical clock plus 10 days and `effective_through` at 30 days after that."
    PRD §3.7: "Writing that prior count as the number of previously lifted suspensions: `reinstatement_fee_cents` is `reinstatement_base_fee_cents` multiplied by the quantity 1 plus `reinstatement_escalation_pct` times the prior count, rounded half up to a whole cent; `probation_days` is 90 whole days multiplied by the prior count plus 1; `suspension_sequence` is the prior count plus 1; and `required_conditions` is fixed as an object with `inspection_required` true, `ecv_attestation_required` true, `min_ecv_contacts` equal to 2 plus the prior count, and `invoices_paid_required` true."
    PRD §3.7: "With the base fee at 60000 cents and the escalation at 0.5, a first suspension carries a 60000-cent reinstatement fee with 90 probation days and 2 callable contacts required, a second carries 90000 cents with 180 days and 3 contacts, a third 120000 cents with 270 days and 4 contacts."
    PRD §3.7: "Serving also issues a `REINSTATEMENT_FEE` invoice against the premises with `suspension_order_id` set, recomputes the premises' `response_status` to `RESPONSE_SUSPENDED` along with its `outstanding_balance_cents` and `renewal_block_active`, and bumps the premises' `version` by 1."
    PRD §3.8: "A `REINSTATEMENT_FEE` invoice carries one REINSTATEMENT line at `reinstatement_base_fee_cents` with `multiplier` equal to 1 plus `reinstatement_escalation_pct` times the premises' prior lifted-suspension count."

    Six chargeable occurrences bring the window count to the inclusive suspension
    threshold of 6, so the sixth ruling auto-proposes an order whose interval runs
    from the clock plus 10 days (2026-09-30T01:00:00Z) through 30 days after that
    (2026-10-30T01:00:00Z). Serving at 2026-09-20T01:00:00Z is at or before that
    start. No suspension has ever been lifted here, so the prior count is 0 and
    all four frozen outputs read off it at once: 60000 * (1 + 0.50 * 0) = 60000,
    90 * (0 + 1) = 90 days, sequence 0 + 1 = 1, and 2 + 0 = 2 callable contacts.
    Its invoice carries one line of 60000 * 1 * 1.00, so the subtotal is 60000, the
    administrative fee is round_half_up(60000 * 0.05) = 3000 inside the
    500..5000 clamp, and the assessment is 63000.

    Design: Corner/calculations/reinstatement_requirement_set_prices_the_first_suspension_at_the_base_fee
    """
    bundle = _site(api, system_count=6)

    incidents = []
    for ordinal in range(5):
        incidents.append(_counted(api, bundle, ordinal))
    sixth_incident, sixth = _counted(api, bundle, 5)
    incidents.append((sixth_incident, sixth))

    assert sixth["occurrence_index"] == 6, sixth["occurrence_index"]
    site = X.get_site(api, bundle.site_id)
    assert site["chargeable_count_window"] == 6, site["chargeable_count_window"]

    orders = X.orders_of_site(api, bundle.site_id)
    assert len(orders) == 1, f"the sixth ruling must auto-propose exactly one order, got {len(orders)}"
    order = orders[0]
    A.assert_status(order, "PROPOSED")
    assert order["basis"] == "EXCESSIVE_FALSE_ALARMS", order["basis"]
    assert order["triggering_incident_id"] == sixth_incident.incident_id, (
        order["triggering_incident_id"]
    )
    assert X.same_instant(order["effective_from"], "2026-09-30T01:00:00Z"), (
        order["effective_from"]
    )
    assert X.same_instant(order["effective_through"], "2026-10-30T01:00:00Z"), (
        order["effective_through"]
    )

    served = A.data_of(api.serve_suspension_order(order["id"], U.PERMIT_CLERK))
    A.assert_status(served, "EFFECTIVE")
    assert served["served_at"] == DETERMINATION_CLOCK, served["served_at"]
    A.assert_money_cents(served["reinstatement_fee_cents"], 60000, "reinstatement_fee_cents")
    assert served["probation_days"] == 90, served["probation_days"]
    assert served["suspension_sequence"] == 1, served["suspension_sequence"]
    assert served["required_conditions"]["min_ecv_contacts"] == 2, served["required_conditions"]

    invoice = A.single(
        api.list_penalty_invoices(
            U.BILLING_CLERK, {"suspension_order_id": order["id"], "kind": "REINSTATEMENT_FEE"}
        )
    )
    A.assert_invoice_totals(
        invoice, subtotal_cents=60000, admin_fee_cents=3000, assessed_cents=63000
    )
