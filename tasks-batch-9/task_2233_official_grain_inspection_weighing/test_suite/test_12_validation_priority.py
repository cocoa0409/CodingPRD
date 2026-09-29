"""Which of two live violations the fixed evaluation order surfaces first."""

from test_helpers import (
    ADMIN,
    INSPECTOR,
    ApiErrorId,
    api_client,
    appeal_payload,
    assert_ledger,
    create_active_inspector,
    create_applicant_account,
    create_certified_instrument,
    create_certified_sampling_device,
    create_designated_area,
    dismiss,
    protein_analysis_payload,
    read_applicant,
    read_certificate,
    read_equipment,
    read_sample,
    record_grading,
    set_clock,
    setup_filed_appeal,
    setup_office,
    setup_sampled_request,
    validate_error,
    validate_paginated,
    BUSINESS_HOURS_CLOCK,
)


APPEAL_WINDOW_SCHEDULES = (
    {
        "service_class": "GRADING",
        "base_fee_cents": 8000,
        "per_thousand_bushel_rate_cents": 2000,
        "minimum_fee_cents": 10000,
    },
    {"service_class": "APPEAL", "base_fee_cents": 20000},
)


def _office_with_short_lived_instrument():
    set_clock(BUSINESS_HOURS_CLOCK)
    area = create_designated_area()
    applicant = create_applicant_account()
    inspector = create_active_inspector(area["id"], "L-1001")
    return {
        "area": area,
        "applicant": applicant,
        "inspector": inspector,
        "probe": create_certified_sampling_device(area["id"], "PROBE-1"),
        "instrument": create_certified_instrument(
            area["id"], "NIR-1", certified_until="2026-08-05T00:00:00Z"
        ),
    }


def test_expired_instrument_is_reported_before_the_exhausted_portion_constraint():
    """When more than one rule could reject a request, the system evaluates them
    in a fixed order and reports only the **first** violation it finds.

    **State** — the entity must be in a state the requested action is declared
    from.

    Any of those three operations attempted when `portions_available` is 0 is
    refused with `ERR_SAMPLE_PORTIONS_EXHAUSTED`.

    Design: Difficulty/priority_pair_validation_conflict/expired_instrument_state_check_outranks_portion_exhaustion_constraint
    """
    office = _office_with_short_lived_instrument()
    staged = setup_sampled_request(
        office, requested_services=("GRADING", "PROTEIN"), portions_count=1
    )
    record_grading(
        staged["request"]["id"], staged["sample"]["id"], office["inspector"]["id"]
    )
    consumed = read_sample(staged["sample"]["id"])
    assert consumed["portions_available"] == 0
    assert consumed["integrity_status"] == "CONSUMED"

    set_clock("2026-08-06T09:00:00Z")

    response = api_client.create_protein_analysis(
        protein_analysis_payload(
            staged["request"]["id"],
            staged["sample"]["id"],
            office["instrument"]["id"],
            office["inspector"]["id"],
        ),
        INSPECTOR,
    )
    validate_error(response, ApiErrorId.ERR_EQUIPMENT_NOT_APPROVED.value, 409)


def test_the_clock_sweep_expires_the_instrument_and_no_analysis_is_written():
    """Three sweeps run: equipment whose `certified_until` is now in the past
    moves from `APPROVED` or `DRIFT_WATCH` to `EXPIRED` and can no longer be
    used for new samples, weighings or analyses; samples whose
    `file_retention_until` has passed move from `SEALED` or `CONSUMED` to
    `EXPIRED` and can no longer be analysed or assigned to an appeal;
    inspectors whose `license_expires_at` has passed move from `ACTIVE` or
    `PROBATIONARY` to `EXPIRED`, and each such inspector's `SCHEDULED` vessel
    watches are aborted with the owning area's `open_watch_count` decremented
    once per aborted watch.

    Any of those three operations attempted when `portions_available` is 0 is
    refused with `ERR_SAMPLE_PORTIONS_EXHAUSTED`.

    Design: Difficulty/priority_pair_validation_conflict/expired_instrument_state_check_outranks_portion_exhaustion_constraint
    """
    office = _office_with_short_lived_instrument()
    staged = setup_sampled_request(
        office, requested_services=("GRADING", "PROTEIN"), portions_count=1
    )
    record_grading(
        staged["request"]["id"], staged["sample"]["id"], office["inspector"]["id"]
    )

    sweep = set_clock("2026-08-06T09:00:00Z")
    assert sweep["expired_equipment_count"] == 1
    assert sweep["expired_sample_count"] == 0
    assert sweep["expired_inspector_count"] == 0

    assert read_equipment(office["instrument"]["id"])["approval_status"] == "EXPIRED"

    api_client.create_protein_analysis(
        protein_analysis_payload(
            staged["request"]["id"],
            staged["sample"]["id"],
            office["instrument"]["id"],
            office["inspector"]["id"],
        ),
        INSPECTOR,
    )
    listed = api_client.list_protein_analyses(ADMIN)
    rows, meta = validate_paginated(listed)
    assert meta["total_count"] == 0
    assert rows == []


def test_a_stale_version_echo_is_refused_before_the_expired_appeal_window():
    """If it does not equal the certificate's current `version`, the filing is
    refused with `ERR_CERTIFICATE_VERSION_CONFLICT` (HTTP 412), the certificate
    is not moved to `UNDER_APPEAL`, and no deposit is charged.

    The consequence of the ordering is worth stating plainly: a suspended area
    surfaces as `ERR_SERVICE_AREA_SUSPENDED` rather than being masked by a
    later portion or fee failure; a stale version echo surfaces as a 412 before
    any state or business rule is consulted; and a fee that would breach the
    credit limit is the very last thing checked, because it can only be
    evaluated after the fee has been computed.

    Design: Difficulty/priority_pair_validation_conflict/stale_certificate_version_outranks_expired_appeal_window
    """
    office = setup_office("DELEGATED", fee_schedules=APPEAL_WINDOW_SCHEDULES)
    staged = setup_filed_appeal(office, appeal_type="REINSPECTION")
    stale_version = staged["certificate"]["version"]
    dismiss(staged["appeal"]["id"])

    set_clock("2026-08-20T09:00:00Z")

    response = api_client.create_appeal(
        appeal_payload(
            staged["certificate"]["id"],
            office["applicant"]["id"],
            stale_version,
            "APPEAL",
        ),
        ADMIN,
    )
    validate_error(response, ApiErrorId.ERR_CERTIFICATE_VERSION_CONFLICT.value, 412)

    certificate = read_certificate(staged["certificate"]["id"])
    assert certificate["status"] == "ISSUED"
    assert certificate["version"] > stale_version
    assert_ledger(
        read_applicant(office["applicant"]["id"]),
        charges=30000,
        credits=10000,
        open_balance=20000,
    )


def test_a_fresh_version_echo_then_surfaces_the_expired_appeal_window():
    """Filing outside the applicable window is `ERR_APPEAL_WINDOW_EXPIRED`.

    Two rights deadlines are computed and stored: `reinspection_deadline_at` is
    exactly 5 days after `issued_at` and `appeal_deadline_at` exactly 10 days
    after `issued_at`.

    Design: Difficulty/priority_pair_validation_conflict/stale_certificate_version_outranks_expired_appeal_window
    """
    office = setup_office("DELEGATED", fee_schedules=APPEAL_WINDOW_SCHEDULES)
    staged = setup_filed_appeal(office, appeal_type="REINSPECTION")
    dismiss(staged["appeal"]["id"])
    set_clock("2026-08-20T09:00:00Z")
    refreshed = read_certificate(staged["certificate"]["id"])
    assert refreshed["appeal_deadline_at"] == "2026-08-13T09:00:00.000Z"

    response = api_client.create_appeal(
        appeal_payload(
            refreshed["id"], office["applicant"]["id"], refreshed["version"], "APPEAL"
        ),
        ADMIN,
    )
    validate_error(response, ApiErrorId.ERR_APPEAL_WINDOW_EXPIRED.value, 422)

    assert read_certificate(refreshed["id"])["status"] == "ISSUED"
