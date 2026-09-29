"""Permit terms, the fourteen clear days, and changing the holder.

Covers the closed-interval term buffer over the (outfitter, area) resource key,
the holder-change condition arms, and the outfitter status ladder.
"""
from test_helpers import (
    ApiErrorId,
    create_outfitter,
    create_published_assessment,
    create_screened_application,
    create_use_area,
    issue_permit,
    read_allocation_summary,
    read_outfitter,
    read_permit,
    set_clock,
    setup_issued_permit,
    validate_error,
    validate_paginated,
    validate_success,
    verify_prequalification,
    api_client,
    TEST_USERS,
)

SPECIALIST = TEST_USERS["permit_specialist_headers"]
OFFICER = TEST_USERS["authorized_officer_headers"]

BETA = {
    "legal_name": "Beta River Guides LLC",
    "ein": "410000002",
    "contact_email": "ops@beta.example",
    "prequalification_insurance_verified": True,
}
DAWN_RIDGE = {
    "legal_name": "Dawn Ridge Outfitters",
    "ein": "410000007",
    "contact_email": "ops@dawnridge.example",
    "prequalification_insurance_verified": False,
}
WILLOW_AREA = {
    "area_code": "WIL-02",
    "name": "Willow Creek Unit",
    "total_allocated_service_days": 2000,
    "reserved_admin_service_days": 0,
}


def _area_with_one_incumbent_2027_term():
    """BRW-01 carrying Alpine's ISSUED 2027 permit, plus a screened 2028
    application from Alpine and one from Beta on the same area."""
    set_clock()
    area = create_use_area()
    create_published_assessment(area["id"], determined_capacity_service_days=900)
    create_published_assessment(
        area["id"], assessment_year=2028, determined_capacity_service_days=900
    )
    alpine = create_outfitter()
    beta = create_outfitter(**BETA)

    incumbent_app = create_screened_application(
        alpine["id"], area["id"], requested_service_days=200
    )
    incumbent = issue_permit(
        incumbent_app["id"], term_start_date="2027-01-01", term_end_date="2027-12-31"
    )
    assert incumbent["administrative_status"] == "ISSUED"

    alpine_2028 = create_screened_application(
        alpine["id"], area["id"], season_year=2028, requested_service_days=200
    )
    beta_2028 = create_screened_application(
        beta["id"], area["id"], season_year=2028, requested_service_days=200
    )
    assert alpine_2028["status"] == "DIRECT_AWARD_PENDING"
    assert beta_2028["status"] == "DIRECT_AWARD_PENDING"
    return {
        "area": area,
        "alpine": alpine,
        "beta": beta,
        "incumbent": incumbent,
        "alpine_2028": alpine_2028,
        "beta_2028": beta_2028,
    }


def test_the_fourteen_clear_days_are_counted_between_closed_intervals():
    """PRD §3.4: "The new term must also stand clear of the holder's other permits in the same
    area. Taking terms as closed intervals, the new permit's term must be separated by at least
    **14 clear days** from the term of any other permit with the same outfitter and the same
    area whose `administrative_status` is `ISSUED`, `ACTIVE` or `SUSPENDED`; overlapping terms,
    terms that merely touch, and gaps of 13 days or fewer are all rejected with
    `ERR_PERMIT_TERM_CONFLICT` (HTTP 409)."
    PRD §3.4: "The officer supplies the `term_start_date` and `term_end_date` bounding the
    authorized term, both inclusive, with the end strictly after the start."
    PRD §2.4: "A request that is rejected writes nothing at all: no field changes, no
    `updated_at` refresh and no `version` increment"

    Design: Difficulty/resource_temporal_overlap/permit_term_closed_interval_fourteen_day_buffer
    """
    stage = _area_with_one_incumbent_2027_term()
    candidate = stage["alpine_2028"]["id"]
    version_before = stage["alpine_2028"]["version"]

    validate_error(
        api_client.issue_permit(
            candidate,
            {
                "term_start_date": "2027-06-01",
                "term_end_date": "2028-05-31",
                "fee_schedule_code": "GRADUATED",
                "indemnification_acknowledged": True,
            },
            OFFICER,
        ),
        ApiErrorId.ERR_PERMIT_TERM_CONFLICT,
    )

    validate_error(
        api_client.issue_permit(
            candidate,
            {
                "term_start_date": "2028-01-01",
                "term_end_date": "2028-12-31",
                "fee_schedule_code": "GRADUATED",
                "indemnification_acknowledged": True,
            },
            OFFICER,
        ),
        ApiErrorId.ERR_PERMIT_TERM_CONFLICT,
    )

    validate_error(
        api_client.issue_permit(
            candidate,
            {
                "term_start_date": "2028-01-14",
                "term_end_date": "2028-12-31",
                "fee_schedule_code": "GRADUATED",
                "indemnification_acknowledged": True,
            },
            OFFICER,
        ),
        ApiErrorId.ERR_PERMIT_TERM_CONFLICT,
    )

    still_pending = validate_success(
        api_client.get_permit_application(candidate, SPECIALIST)
    )
    assert still_pending["status"] == "DIRECT_AWARD_PENDING"
    assert still_pending["version"] == version_before

    granted = validate_success(
        api_client.issue_permit(
            candidate,
            {
                "term_start_date": "2028-01-15",
                "term_end_date": "2028-12-31",
                "fee_schedule_code": "GRADUATED",
                "indemnification_acknowledged": True,
            },
            OFFICER,
        ),
        201,
    )
    assert granted["administrative_status"] == "ISSUED"
    assert granted["term_start_date"].startswith("2028-01-15")
    assert granted["authorized_service_days"] == 200
    assert granted["predecessor_permit_id"] is None


def test_the_buffer_is_scoped_to_one_holder_so_a_rival_may_take_the_refused_term():
    """PRD §3.4: "the new permit's term must be separated by at least **14 clear days** from the
    term of any other permit with the same outfitter and the same area whose
    `administrative_status` is `ISSUED`, `ACTIVE` or `SUSPENDED`"
    PRD §2.7: "The governing invariant is that the allocatable total always equals the committed
    sum plus the pending sum plus the available remainder, for every area at every observable
    instant."
    PRD §2.7: "`demand_ratio` is the committed sum plus the pending sum, divided by the
    allocatable total, rounded half up to four decimal places."

    Design: Difficulty/resource_temporal_overlap/permit_term_closed_interval_fourteen_day_buffer
    """
    stage = _area_with_one_incumbent_2027_term()
    area_id = stage["area"]["id"]
    contested_term = {
        "term_start_date": "2028-01-01",
        "term_end_date": "2028-12-31",
        "fee_schedule_code": "GRADUATED",
        "indemnification_acknowledged": True,
    }

    validate_error(
        api_client.issue_permit(stage["alpine_2028"]["id"], contested_term, OFFICER),
        ApiErrorId.ERR_PERMIT_TERM_CONFLICT,
    )

    beta_permit = validate_success(
        api_client.issue_permit(stage["beta_2028"]["id"], dict(contested_term), OFFICER),
        201,
    )
    assert beta_permit["administrative_status"] == "ISSUED"
    assert beta_permit["outfitter_id"] == stage["beta"]["id"]
    assert beta_permit["use_area_id"] == area_id
    assert beta_permit["authorized_service_days"] == 200

    alpine_permit = validate_success(
        api_client.issue_permit(
            stage["alpine_2028"]["id"],
            {
                "term_start_date": "2028-01-15",
                "term_end_date": "2028-12-31",
                "fee_schedule_code": "GRADUATED",
                "indemnification_acknowledged": True,
            },
            OFFICER,
        ),
        201,
    )
    assert alpine_permit["outfitter_id"] == stage["alpine"]["id"]

    summary = read_allocation_summary(area_id)
    assert summary["allocatable_service_days"] == 900
    assert summary["committed_service_days"] == 600
    assert summary["pending_service_days"] == 0
    assert summary["available_service_days"] == 300
    assert summary["demand_ratio"] == 0.6667
    assert summary["allocation_posture"] == "OPEN"

    permits, meta = validate_paginated(
        api_client.list_permits(SPECIALIST, params={"use_area_id": area_id})
    )
    assert meta["total_count"] == 3
    assert [row["id"] for row in permits] == [
        stage["incumbent"]["id"],
        beta_permit["id"],
        alpine_permit["id"],
    ], "permit listings come back oldest first"


def test_the_identical_transfer_is_refused_then_granted_on_a_flag_of_the_other_party():
    """PRD §3.9: "The transfer conditions are strict and all carry one error,
    `ERR_TRANSFER_NOT_PERMITTED`: the permit's `compliance_status` must be `COMPLIANT`, its
    `administrative_status` must be `ISSUED` or `ACTIVE`, its `suspension_count` must be 0, the
    incoming outfitter's `prequalification_insurance_verified` must be true, the incoming
    outfitter must differ from the current holder, and the permit must not already be the
    product of a transfer — a permit may change hands at most **once**, which is tracked by the
    presence of a `predecessor_permit_id` on the permit being transferred."
    PRD §3.9: "The successor's `term_start_date` is always the calendar day immediately after the
    predecessor's `term_end_date`, and the caller's `successor_term_end_date` must fall strictly
    after that computed start; a `successor_term_end_date` on or before the predecessor's
    `term_end_date` describes a backdated term with no forward coverage and is refused with
    `ERR_SUCCESSION_TERM_NOT_CONTIGUOUS`."
    PRD §3.9: "a successor permit is created in `administrative_status` `ISSUED` and
    `compliance_status` `COMPLIANT`, carrying the same `use_area_id`, `application_id` and
    `authorized_service_days`, the new holder's `outfitter_id`, `predecessor_permit_id` pointing
    back at the closed permit, and `indemnification_acknowledged` false."
    PRD §3.9: "The area's `committed_service_days` is unchanged across the pair: the predecessor
    releases exactly what the successor commits, in the same request, so no observer sees the
    days in flight. Finally the counts and `status` of *both* the outgoing and the incoming
    outfitter are re-derived."
    PRD §3.1: "The first matching rule wins: at least one active permit makes the outfitter
    `PERMITTED`; otherwise at least one suspended permit makes it `SUSPENDED`; otherwise at
    least one held permit still makes it `PERMITTED`; otherwise it falls back to `APPLICANT`."

    Design: Corner/validations/holder_change_rules_apply_only_to_the_configured_incoming_holder
    """
    context = setup_issued_permit(
        outfitter_overrides={"prequalification_insurance_verified": True},
        application_overrides={"requested_service_days": 200},
        permit_overrides={"term_start_date": "2027-01-01", "term_end_date": "2029-12-31"},
    )
    alpine = context["outfitter"]
    p1 = context["permit"]
    dawn = create_outfitter(**DAWN_RIDGE)
    assert dawn["prequalification_insurance_verified"] is False
    assert p1["suspension_count"] == 0
    assert p1["predecessor_permit_id"] is None

    transfer = {"incoming_outfitter_id": dawn["id"], "successor_term_end_date": "2031-12-31"}

    validate_error(
        api_client.change_permit_holder(p1["id"], dict(transfer), OFFICER),
        ApiErrorId.ERR_TRANSFER_NOT_PERMITTED,
    )
    validate_error(
        api_client.change_permit_holder(
            p1["id"],
            {"incoming_outfitter_id": alpine["id"], "successor_term_end_date": "2031-12-31"},
            OFFICER,
        ),
        ApiErrorId.ERR_TRANSFER_NOT_PERMITTED,
    )

    verify_prequalification(dawn["id"], True)

    validate_error(
        api_client.change_permit_holder(
            p1["id"],
            {"incoming_outfitter_id": dawn["id"], "successor_term_end_date": "2029-06-30"},
            OFFICER,
        ),
        ApiErrorId.ERR_SUCCESSION_TERM_NOT_CONTIGUOUS,
    )

    p2 = validate_success(
        api_client.change_permit_holder(p1["id"], dict(transfer), OFFICER), 201
    )
    assert p2["administrative_status"] == "ISSUED"
    assert p2["compliance_status"] == "COMPLIANT"
    assert p2["outfitter_id"] == dawn["id"]
    assert p2["use_area_id"] == context["use_area"]["id"]
    assert p2["application_id"] == context["application"]["id"]
    assert p2["authorized_service_days"] == 200
    assert p2["predecessor_permit_id"] == p1["id"]
    assert p2["indemnification_acknowledged"] is False
    assert p2["term_start_date"].startswith("2030-01-01"), (
        "the successor start is the day after the predecessor's term_end_date"
    )

    assert read_permit(p1["id"])["administrative_status"] == "CLOSED"

    validate_error(
        api_client.change_permit_holder(
            p2["id"],
            {"incoming_outfitter_id": alpine["id"], "successor_term_end_date": "2033-12-31"},
            OFFICER,
        ),
        ApiErrorId.ERR_TRANSFER_NOT_PERMITTED,
    )

    summary = read_allocation_summary(context["use_area"]["id"])
    assert summary["committed_service_days"] == 200
    assert summary["pending_service_days"] == 0
    assert summary["available_service_days"] == 700

    outgoing = read_outfitter(alpine["id"])
    assert outgoing["status"] == "APPLICANT"
    assert outgoing["active_permit_count"] == 0
    assert outgoing["prior_permit_count"] == 1
    incoming = read_outfitter(dawn["id"])
    assert incoming["status"] == "PERMITTED"
    assert incoming["active_permit_count"] == 0
    assert incoming["prior_permit_count"] == 1


def test_the_status_ladder_falls_through_to_held_and_walks_back_down_to_applicant():
    """PRD §3.1: "An outfitter's `status` is never set directly. It is re-derived after every
    change to any of its permits' `administrative_status` and after a holder change, from three
    counts taken over all of that outfitter's permits with no time window: how many are `ACTIVE`,
    how many are `SUSPENDED`, and how many are held at all (that is, `ISSUED`, `ACTIVE` or
    `SUSPENDED`). The first matching rule wins: at least one active permit makes the outfitter
    `PERMITTED`; otherwise at least one suspended permit makes it `SUSPENDED`; otherwise at least
    one held permit still makes it `PERMITTED`; otherwise it falls back to `APPLICANT`."
    PRD §3.1: "The same derivation republishes `active_permit_count` as the number of `ACTIVE`
    permits and `prior_permit_count` as the count of *every* permit ever issued to the outfitter
    in *any* administrative status, `ISSUED` included — so an outfitter that has never held a
    permit is the only case reading 0."
    PRD §3.8: "Revocation releases the committed allocation — the area's `committed_service_days`
    drops by the permit's `authorized_service_days`, and `available_service_days`, `demand_ratio`
    and `allocation_posture` are recomputed, along with the governing assessment's allocation
    figures — revokes every `AUTHORIZED` authorization with reason `PERMIT_CLOSED`, closes every
    assessment on the permit whose `balance_due_cents` is zero while leaving assessments that
    still carry a balance untouched, and recomputes the holder's counts and `status`."

    Design: Corner/calculations/outfitter_status_propagation_terminates_and_leaves_prior_permit_count_intact
    """
    set_clock()
    alpine = create_outfitter(prequalification_insurance_verified=True)
    fresh = read_outfitter(alpine["id"])
    assert fresh["status"] == "APPLICANT"
    assert fresh["active_permit_count"] == 0
    assert fresh["prior_permit_count"] == 0

    bear = create_use_area()
    create_published_assessment(bear["id"], determined_capacity_service_days=900)
    willow = create_use_area(**WILLOW_AREA)
    create_published_assessment(willow["id"], determined_capacity_service_days=2000)

    bear_app = create_screened_application(
        alpine["id"], bear["id"], requested_service_days=200
    )
    p1 = issue_permit(
        bear_app["id"], term_start_date="2027-01-01", term_end_date="2029-12-31"
    )
    willow_app = create_screened_application(
        alpine["id"],
        willow["id"],
        requested_service_days=300,
        proposed_activity_type="MOUNTAINEERING",
    )
    p2 = issue_permit(
        willow_app["id"], term_start_date="2027-01-01", term_end_date="2029-12-31"
    )
    assert p1["administrative_status"] == "ISSUED"
    assert p2["administrative_status"] == "ISSUED"

    both_held = read_outfitter(alpine["id"])
    assert both_held["status"] == "PERMITTED", (
        "the ladder falls past ACTIVE and SUSPENDED to the held branch"
    )
    assert both_held["active_permit_count"] == 0
    assert both_held["prior_permit_count"] == 2

    validate_success(
        api_client.revoke_permit(
            p1["id"], {"revocation_reason_code": "HOLDER_SURRENDER"}, OFFICER
        )
    )
    one_held = read_outfitter(alpine["id"])
    assert one_held["status"] == "PERMITTED"
    assert one_held["active_permit_count"] == 0
    assert one_held["prior_permit_count"] == 2

    validate_success(
        api_client.revoke_permit(
            p2["id"], {"revocation_reason_code": "HOLDER_SURRENDER"}, OFFICER
        )
    )
    none_held = read_outfitter(alpine["id"])
    assert none_held["status"] == "APPLICANT"
    assert none_held["active_permit_count"] == 0
    assert none_held["prior_permit_count"] == 2, (
        "prior_permit_count has no status filter, so a fully revoked history still counts"
    )

    bear_summary = read_allocation_summary(bear["id"])
    assert bear_summary["committed_service_days"] == 0
    assert bear_summary["pending_service_days"] == 0
    assert bear_summary["available_service_days"] == 900
    willow_summary = read_allocation_summary(willow["id"])
    assert willow_summary["committed_service_days"] == 0
    assert willow_summary["pending_service_days"] == 0
    assert willow_summary["available_service_days"] == 2000
