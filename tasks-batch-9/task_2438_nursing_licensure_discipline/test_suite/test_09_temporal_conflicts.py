"""Two interval rules with opposite endpoint conventions."""
from test_helpers import (
    INVESTIGATOR,
    PRESIDING,
    ApiClient,
    ApiErrorId,
    assert_monitoring_agreement,
    evidence_request_payload,
    monitoring_agreement_payload,
    reread_agreement,
    reread_complaint,
    seed_active_license,
    seed_atd_offered_complaint,
    seed_custodian_holds,
    seed_investigated_complaint,
    seed_monitoring_agreement,
    validate_error,
    validate_paginated,
    validate_success,
)


def _two_diversion_eligible_complaints(api: ApiClient):
    """One nurse, two substance-use complaints at ATD_OFFERED, one agreement
    already offered against the first of them."""
    ctx = seed_active_license(
        api,
        program_overrides={
            "program_code": "OH-BSN-99",
            "program_name": "Portsmouth BSN",
            "degree_level": "BSN",
            "nclex_first_time_pass_rate_bp": 8050,
        },
        nurse_overrides={"full_name": "Cyrus Ellingham", "birth_year": 1984,
                         "ssn_last4": "9900"},
    )
    first = seed_atd_offered_complaint(
        api, ctx["license_id"], page_count=15,
        evidence_overrides={
            "record_class": "EMPLOYER_PERSONNEL",
            "custodian_code": "MERCY-GEN",
            "hold_start_at": "2026-08-02T00:00:00Z",
            "hold_end_at": "2026-08-25T00:00:00Z",
        },
        incident_date="2026-06-05T00:00:00Z",
        employer_custodian_codes=["MERCY-GEN"],
    )
    second = seed_atd_offered_complaint(
        api, ctx["license_id"], page_count=11,
        evidence_overrides={
            "record_class": "EMPLOYER_PERSONNEL",
            "custodian_code": "ST-LUKE",
            "hold_start_at": "2026-08-02T00:00:00Z",
            "hold_end_at": "2026-08-25T00:00:00Z",
        },
        incident_date="2026-06-25T00:00:00Z",
        employer_custodian_codes=["ST-LUKE"],
    )
    ctx["first_complaint_id"] = first["id"]
    ctx["second_complaint_id"] = second["id"]
    ctx["first_agreement"] = seed_monitoring_agreement(
        api, ctx["nurse_id"], first["id"],
        start_date="2026-09-01T00:00:00Z", end_date="2027-09-01T00:00:00Z",
    )
    return ctx


def test_new_monitoring_period_inside_the_clearance_buffer_is_refused(api: ApiClient):
    """PRD §3.7: "The proposed period, running from `start_date` through
    `end_date` inclusive, must not intersect the period of any existing agreement
    of the same nurse whose `status` is `OFFERED`, `EXECUTED`, `ACTIVE`,
    `SUSPENDED_PENDING_REVIEW`, `COMPLETED`, or `BREACHED` — completed and
    breached history still blocks, only a `TERMINATED` agreement does not — and
    the new `start_date` must fall strictly after the prior agreement's
    `end_date` advanced by the board's `monitoring_clearance_gap_days`."

    PRD §3.7: "Because the interval is closed, touching endpoints conflict: a new
    `start_date` exactly equal to a prior `end_date` is a conflict, and so is a
    `start_date` landing anywhere inside the clearance buffer."

    PRD §3.7: "Any such collision is refused with
    `ERR_MONITORING_PERIOD_CONFLICT`."

    PRD §2.5: "`monitoring_clearance_gap_days` defaults to 90 and is the number
    of clear days that must separate a nurse's prior monitoring agreement from a
    new one."

    Design: Difficulty/resource_temporal_overlap/monitoring_agreement_closed_interval_clearance_gap_conflict
    """
    ctx = _two_diversion_eligible_complaints(api)

    response = api.create_monitoring_agreement(
        monitoring_agreement_payload(ctx["nurse_id"], ctx["second_complaint_id"],
                                     start_date="2027-11-01T00:00:00Z",
                                     end_date="2028-11-01T00:00:00Z"),
        PRESIDING,
    )

    validate_error(response, ApiErrorId.ERR_MONITORING_PERIOD_CONFLICT.value)
    first = reread_agreement(api, ctx["first_agreement"]["id"])
    assert first["status"] == "OFFERED", (
        f"The rejected offer left the prior agreement alone, got {first['status']}"
    )
    assert first["version"] == ctx["first_agreement"]["version"], (
        "A rejected offer mutates no existing agreement"
    )


def test_monitoring_period_starting_past_the_buffer_is_accepted(api: ApiClient):
    """PRD §3.7: "Monitoring periods for one nurse may not overlap, and unlike
    the evidence-hold rule this interval is **closed** at both ends and carries a
    clearance buffer."

    PRD §3.7: "A new agreement takes `status` `OFFERED`, with
    `compliance_report_count` and `missed_screen_count` both 0 and `executed_at`
    null."

    PRD §3.7: "The offering board member's own identity is recorded in
    `approved_by_user_id`, which is what later disqualifies that member from
    voting on the same nurse."

    Design: Difficulty/resource_temporal_overlap/monitoring_agreement_closed_interval_clearance_gap_conflict
    """
    ctx = _two_diversion_eligible_complaints(api)

    created = validate_success(
        api.create_monitoring_agreement(
            monitoring_agreement_payload(ctx["nurse_id"], ctx["second_complaint_id"],
                                         start_date="2027-12-01T00:00:00Z",
                                         end_date="2028-12-01T00:00:00Z"),
            PRESIDING,
        ),
        201,
    )

    assert_monitoring_agreement(created)
    assert created["status"] == "OFFERED"
    assert created["start_date"].startswith("2027-12-01T00:00:00"), (
        f"The accepted period starts past the buffer, got {created['start_date']}"
    )
    assert created["compliance_report_count"] == 0
    assert created["missed_screen_count"] == 0
    assert created["executed_at"] is None
    assert created["approved_by_user_id"] == "bm-presiding"

    agreements, meta = validate_paginated(
        api.list_monitoring_agreements(PRESIDING,
                                       params={"nurse_id": ctx["nurse_id"], "limit": 100})
    )
    assert meta["total_count"] == 2, (
        f"Exactly two agreements exist for this nurse, got {meta['total_count']}"
    )
    assert len(agreements) == 2
    assert reread_complaint(api, ctx["second_complaint_id"])["status"] == "ATD_OFFERED"


def _saturated_custodian(api: ApiClient):
    """An open investigation with two overlapping holds already on one custodian."""
    ctx = seed_active_license(
        api,
        program_overrides={
            "program_code": "OH-BSN-77",
            "program_name": "Marietta BSN",
            "degree_level": "BSN",
            "nclex_first_time_pass_rate_bp": 8150,
        },
        nurse_overrides={"full_name": "Yara Petrossian", "birth_year": 1990,
                         "ssn_last4": "2468"},
    )
    complaint = seed_investigated_complaint(
        api, ctx["license_id"],
        complainant_type="EMPLOYER",
        violation_category="PRACTICE_STANDARD",
        incident_date="2026-07-01T00:00:00Z",
        employer_custodian_codes=["MERCY-GEN"],
    )
    ctx["complaint_id"] = complaint["id"]
    ctx["holds"] = seed_custodian_holds(
        api, complaint["id"],
        [("2026-08-05T00:00:00Z", "2026-09-05T00:00:00Z"),
         ("2026-08-20T00:00:00Z", "2026-09-20T00:00:00Z")],
        record_class="EMPLOYER_PERSONNEL",
        custodian_code="MERCY-GEN",
    )
    return ctx


def test_third_overlapping_hold_on_one_custodian_is_refused(api: ApiClient):
    """PRD §3.6: "The system counts the existing demands, across every complaint
    in the system, that carry the same `custodian_code`, hold a `status` of
    `REQUESTED` or `PRODUCED`, and whose hold window overlaps the requested one."

    PRD §3.6: "If that count has already reached the board's
    `max_concurrent_custodian_holds`, the demand is refused with
    `ERR_CUSTODIAN_HOLD_CAPACITY`."

    PRD §2.5: "`max_concurrent_custodian_holds` defaults to 2 and caps how many
    mutually overlapping record holds one custodian may bear."

    Design: Difficulty/resource_temporal_overlap/custodian_hold_half_open_capacity_refuses_third_concurrent_hold
    """
    ctx = _saturated_custodian(api)

    response = api.create_evidence_request(
        ctx["complaint_id"],
        evidence_request_payload(record_class="EMPLOYER_PERSONNEL",
                                 custodian_code="MERCY-GEN",
                                 hold_start_at="2026-09-01T00:00:00Z",
                                 hold_end_at="2026-10-01T00:00:00Z"),
        INVESTIGATOR,
    )

    validate_error(response, ApiErrorId.ERR_CUSTODIAN_HOLD_CAPACITY.value)


def test_hold_starting_exactly_when_another_ends_does_not_compete(api: ApiClient):
    """PRD §3.6: "Overlap is half-open: two windows overlap when the first starts
    strictly before the second ends and the second starts strictly before the
    first ends, so windows that merely touch — one ending exactly when the next
    begins — do not overlap and do not compete."

    PRD §3.6: "A new demand takes `status` `REQUESTED` and `page_count` 0, with
    `produced_at` null."

    PRD §3.6: "**Records demands** are issued under an open investigation, and
    each one places a hold on a custodian's files."

    Design: Difficulty/resource_temporal_overlap/custodian_hold_half_open_capacity_refuses_third_concurrent_hold
    """
    ctx = _saturated_custodian(api)

    created = validate_success(
        api.create_evidence_request(
            ctx["complaint_id"],
            evidence_request_payload(record_class="EMPLOYER_PERSONNEL",
                                     custodian_code="MERCY-GEN",
                                     hold_start_at="2026-09-20T00:00:00Z",
                                     hold_end_at="2026-10-20T00:00:00Z"),
            INVESTIGATOR,
        ),
        201,
    )

    assert created["status"] == "REQUESTED"
    assert created["page_count"] == 0
    assert created["produced_at"] is None

    demands, meta = validate_paginated(
        api.list_complaint_evidence_requests(ctx["complaint_id"], INVESTIGATOR,
                                             params={"limit": 100})
    )
    assert meta["total_count"] == 3, (
        f"Two original holds plus the touching one is 3, got {meta['total_count']}"
    )
    for original in ctx["holds"]:
        match = [demand for demand in demands if demand["id"] == original["id"]]
        assert match and match[0]["status"] == "REQUESTED", (
            "Both original holds are untouched by the new demand"
        )
    assert reread_complaint(api, ctx["complaint_id"])["status"] == "INVESTIGATION_OPEN"
