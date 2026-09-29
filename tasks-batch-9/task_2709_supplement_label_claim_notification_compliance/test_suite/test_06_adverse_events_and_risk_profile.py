"""Adverse event intake, triage, agency filing and the risk profile read.

Triage is the fork that decides whether a report ever acquires a filing deadline,
and every triage recomputes the product's compliance risk index and posture in
the same request.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers.api_errors import ERR_AER_STATE_INVALID
from test_helpers.assertions import (
    assert_calendar_date,
    assert_instant,
    assert_posture,
    assert_risk_index,
)
from test_helpers.constants import (
    AER_SUBMITTED_TO_FDA,
    AER_TRIAGED_NONSERIOUS,
    AER_TRIAGED_SERIOUS,
    OUTCOME_HOSPITALIZATION,
    OUTCOME_OTHER,
    POSTURE_OPEN,
    REPORTER_CONSUMER,
    REPORTER_HEALTHCARE_PROVIDER,
    TIMELINESS_TIMELY,
)
from test_helpers.factories import aer_submission_payload
from test_helpers.fixtures import (
    make_aer,
    make_product,
    make_triaged_nonserious_aer,
    make_triaged_serious_aer,
    set_clock,
)


def test_the_nonserious_branch_mints_no_filing_deadline(
    api, specialist_headers, quality_headers
):
    """A report with no serious outcome code leaves the deadline null.

    PRD §3.8: "The non-serious branch fires when the array contains none of the five
    serious outcomes **and** ``serious_override`` is absent or false: it sets
    ``is_serious`` false, drives ``RECEIVED → TRIAGED_NONSERIOUS``, stamps
    ``triaged_at``, leaves ``submission_due_date`` null, increments the product's
    ``nonserious_ae_count`` by 1, and advances the report's ``version``." The same
    section pins the weight: "a serious event is worth 20 index points and a
    non-serious one 6".

    Design: Corner/state_machines/corner_nonserious_aer_branch_mints_no_submission_deadline
    """
    product = make_product(
        api,
        specialist_headers,
        brand_name="NutraCore",
        product_name="Fiber Blend",
        net_quantity_g=300,
        servings_per_container=30,
    )
    report = make_aer(
        api,
        product["id"],
        quality_headers,
        reporter_type=REPORTER_CONSUMER,
        received_date="2026-08-03",
        narrative="Transient bloating that resolved without care.",
        outcome_codes=[OUTCOME_OTHER],
    )

    triaged = validate_success(
        api.triage_adverse_event_report(report["id"], quality_headers), 200
    )
    assert triaged["aer_status"] == AER_TRIAGED_NONSERIOUS
    assert triaged["is_serious"] is False
    assert triaged["submission_due_date"] is None
    assert_instant(triaged["triaged_at"], "2026-08-01T00:00:00Z")
    assert_calendar_date(triaged["retention_until"], "2032-08-03")

    reread = validate_success(api.get_product(product["id"], specialist_headers), 200)
    assert reread["nonserious_ae_count"] == 1
    assert reread["serious_ae_count"] == 0
    assert_risk_index(reread, 16)
    assert_posture(reread, POSTURE_OPEN)


def test_a_filed_report_refuses_a_second_filing(
    api, specialist_headers, quality_headers
):
    """``SUBMITTED_TO_FDA`` is terminal, so the reference is never overwritten.

    PRD §3.8: "``SUBMITTED_TO_FDA`` is terminal, and because it is one of the two
    statuses counted by ``serious_ae_count``, filing a report never reduces the
    product's risk index." PRD §2.7 rank 9 adds that "An adverse event report must be
    in ``RECEIVED`` to be triaged and in ``TRIAGED_SERIOUS`` to be filed with the
    agency, otherwise ``ERR_AER_STATE_INVALID``".

    Design: Corner/state_machines/corner_submitted_aer_is_terminal_and_refuses_resubmission
    """
    product = make_product(
        api,
        specialist_headers,
        brand_name="NutraCore",
        product_name="Sleep Support",
        net_quantity_g=90,
        servings_per_container=45,
    )
    report = make_triaged_serious_aer(
        api,
        product["id"],
        quality_headers,
        reporter_type=REPORTER_HEALTHCARE_PROVIDER,
        received_date="2026-07-28",
        narrative="Overnight admission for arrhythmia.",
        outcome_codes=[OUTCOME_HOSPITALIZATION],
    )
    assert report["aer_status"] == AER_TRIAGED_SERIOUS
    assert_calendar_date(report["submission_due_date"], "2026-08-18")

    filed = validate_success(
        api.submit_aer_to_fda(
            report["id"], aer_submission_payload("SAE-2026-0900"), specialist_headers
        ),
        200,
    )
    assert filed["aer_status"] == AER_SUBMITTED_TO_FDA
    assert filed["submission_timeliness"] == TIMELINESS_TIMELY
    assert filed["submission_reference"] == "SAE-2026-0900"

    refused = api.submit_aer_to_fda(
        report["id"], aer_submission_payload("SAE-2026-0901"), specialist_headers
    )
    validate_error(refused, ERR_AER_STATE_INVALID, 409)

    reread = validate_success(
        api.get_adverse_event_report(report["id"], quality_headers), 200
    )
    assert reread["submission_reference"] == "SAE-2026-0900"
    assert reread["submission_timeliness"] == TIMELINESS_TIMELY
    assert reread["aer_status"] == AER_SUBMITTED_TO_FDA

    product_after = validate_success(
        api.get_product(product["id"], specialist_headers), 200
    )
    assert product_after["late_notification_count"] == 0
    assert product_after["serious_ae_count"] == 1


def test_the_risk_profile_read_agrees_with_the_stored_counters(
    api, specialist_headers, quality_headers, auditor_headers
):
    """One serious event lands exactly on the middle escalation tier.

    PRD §2.9: "A base below 30 attracts no surcharge; a base of at least 30 but below
    60 attracts a surcharge of 5; a base of 60 or more attracts a surcharge of 12."
    PRD §3.8 states the same arithmetic in words: "a single serious report moves a
    pristine product from an index of 10 to an index of 30, and the escalation tier
    that base selects pushes the stored index to 35."

    Design: Corner/endpoints/corner_risk_profile_read_matches_the_stored_counters
    """
    product = make_product(
        api,
        specialist_headers,
        brand_name="NutraCore",
        product_name="Sleep Support",
        net_quantity_g=90,
        servings_per_container=45,
    )
    make_triaged_serious_aer(
        api,
        product["id"],
        quality_headers,
        reporter_type=REPORTER_HEALTHCARE_PROVIDER,
        received_date="2026-07-30",
        narrative="Overnight admission for tachycardia.",
        outcome_codes=[OUTCOME_HOSPITALIZATION],
    )

    profile = validate_success(api.get_risk_profile(product["id"], auditor_headers), 200)
    assert_risk_index(profile, 35)
    assert profile["serious_ae_count"] == 1
    assert profile["nonserious_ae_count"] == 0
    assert profile["late_notification_count"] == 0
    assert profile["rejected_coa_count"] == 0
    assert_posture(profile, POSTURE_OPEN)


def test_the_logical_clock_drives_the_triage_stamp_but_not_the_deadline(
    api, specialist_headers, quality_headers
):
    """Moving logical now changes ``triaged_at`` and leaves the deadline anchored.

    PRD §3.8: "That branch sets ``is_serious`` true, drives ``RECEIVED →
    TRIAGED_SERIOUS``, stamps ``triaged_at`` from the logical clock, mints a
    ``submission_due_date``". The deadline has a different anchor: "Starting from
    ``received_date`` as day zero, which is itself never counted, the calendar is
    walked forward one day at a time; a day that falls on Monday, Tuesday, Wednesday,
    Thursday or Friday increments the count, while a Saturday or a Sunday is skipped
    without counting."

    Design: Corner/endpoints/corner_clock_endpoint_drives_logical_time_for_derived_dates
    """
    product = make_product(
        api,
        specialist_headers,
        brand_name="NutraCore",
        product_name="Joint Relief",
        net_quantity_g=60,
        servings_per_container=30,
    )
    report = make_aer(
        api,
        product["id"],
        quality_headers,
        reporter_type=REPORTER_CONSUMER,
        received_date="2026-09-01",
        narrative="Admitted for observation after a fall.",
        outcome_codes=[OUTCOME_HOSPITALIZATION],
    )
    assert_calendar_date(report["retention_until"], "2032-09-01")

    set_clock(api, "2026-09-07T12:00:00Z", quality_headers)
    triaged = validate_success(
        api.triage_adverse_event_report(report["id"], quality_headers), 200
    )
    assert triaged["aer_status"] == AER_TRIAGED_SERIOUS
    assert triaged["is_serious"] is True
    assert_instant(triaged["triaged_at"], "2026-09-07T12:00:00Z")
    assert_calendar_date(triaged["submission_due_date"], "2026-09-22")
    assert_calendar_date(triaged["retention_until"], "2032-09-01")

    reread = validate_success(api.get_product(product["id"], specialist_headers), 200)
    assert reread["serious_ae_count"] == 1
    assert_risk_index(reread, 35)


def test_a_cascaded_counter_is_readable_on_the_very_next_request(
    api, specialist_headers, quality_headers
):
    """No settling delay: the third triage is already visible on the product.

    PRD §3.8: "Both branches recompute the product's ``compliance_risk_index`` and
    then its ``label_posture``, and the weights differ by more than a factor of
    three — a serious event is worth 20 index points and a non-serious one 6".
    PRD §2.9 pins the tier: "a base of at least 30 but below 60 attracts a surcharge
    of 5".

    Design: Corner/consistency_model/corner_derived_counters_visible_in_the_same_response
    """
    product = make_product(
        api,
        specialist_headers,
        brand_name="NutraCore",
        product_name="Joint Relief",
        net_quantity_g=60,
        servings_per_container=30,
    )
    make_triaged_nonserious_aer(
        api,
        product["id"],
        quality_headers,
        reporter_type=REPORTER_CONSUMER,
        received_date="2026-07-20",
        narrative="Mild nausea for one day.",
        outcome_codes=[OUTCOME_OTHER],
    )
    make_triaged_nonserious_aer(
        api,
        product["id"],
        quality_headers,
        reporter_type=REPORTER_CONSUMER,
        received_date="2026-07-24",
        narrative="Transient headache.",
        outcome_codes=[OUTCOME_OTHER],
    )
    standing = validate_success(api.get_product(product["id"], specialist_headers), 200)
    assert standing["nonserious_ae_count"] == 2
    assert_risk_index(standing, 22)

    third = make_aer(
        api,
        product["id"],
        quality_headers,
        reporter_type=REPORTER_HEALTHCARE_PROVIDER,
        received_date="2026-07-28",
        narrative="Emergency room visit with arrhythmia.",
        outcome_codes=[OUTCOME_HOSPITALIZATION],
    )
    triaged = validate_success(
        api.triage_adverse_event_report(third["id"], quality_headers), 200
    )
    assert triaged["aer_status"] == AER_TRIAGED_SERIOUS
    assert_calendar_date(triaged["submission_due_date"], "2026-08-18")

    immediately = validate_success(
        api.get_product(product["id"], quality_headers), 200
    )
    assert_risk_index(immediately, 47)
    assert_posture(immediately, POSTURE_OPEN)
    assert immediately["serious_ae_count"] == 1
    assert immediately["nonserious_ae_count"] == 2
