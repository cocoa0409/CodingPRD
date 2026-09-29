"""The permit's two independent status dimensions, and what a terminal state refuses.

Covers the four combined states one permit walks through, the compliance ladder
running underneath an ISSUED permit, and the absorbing behaviour of REVOKED,
SUPERSEDED and a revoked authorization.
"""
from test_helpers import (
    ApiErrorId,
    authorize_guide,
    create_outfitter,
    create_published_assessment,
    create_qualified_guide,
    cure_action,
    insurance_certificate_payload,
    issue_noncompliance_action,
    list_permit_authorizations,
    read_allocation_summary,
    read_needs_assessment_list,
    read_outfitter,
    read_permit,
    setup_active_permit,
    setup_issued_permit,
    trip_use_report_payload,
    validate_error,
    validate_success,
    api_client,
    LEAD_WFR_GUIDE,
    TEST_USERS,
)

SPECIALIST = TEST_USERS["permit_specialist_headers"]
OFFICER = TEST_USERS["authorized_officer_headers"]
CEDAR = {
    "legal_name": "Cedar Creek Guides LLC",
    "ein": "410000002",
    "contact_email": "ops@cedar.example",
    "prequalification_insurance_verified": True,
}


def test_one_permit_walks_four_combined_states_and_reinstatement_closes_the_loop():
    """PRD §3.4: "The two status dimensions are genuinely independent. `administrative_status`
    answers "may the holder operate" and takes values `ISSUED`, `ACTIVE`, `SUSPENDED`, `REVOKED`,
    `EXPIRED` and `CLOSED`, of which the last three are terminal. `compliance_status` answers "is
    the holder in good standing" and takes values `COMPLIANT`, `PROBATION` and `NONCOMPLIANT`,
    none of them terminal. They advance on different triggers and their value sets are disjoint,
    so a permit legitimately carries a pair such as `ACTIVE` with `PROBATION`, or `SUSPENDED` with
    `NONCOMPLIANT`."
    PRD §3.8: "Otherwise, if `open_noncompliance_points` is at or above **5**, or
    `insurance_current` is false, or `fee_delinquent` is true, the permit is on `PROBATION`."
    PRD §3.8: "Whatever the trigger, suspension increments `suspension_count`, stamps the date and
    reason, revokes every `AUTHORIZED` authorization on the permit with reason `PERMIT_SUSPENDED`
    so that `authorized_client_capacity_total` recomputes to 0, and then recomputes the holder's
    `active_permit_count` and re-derives its `status`, which falls from `PERMITTED` to `SUSPENDED`
    once the holder has no active permits left and at least one suspended one."
    PRD §3.8: "A cured action is terminal and stops contributing points, so a cure can pull the
    permit back below a threshold; it never auto-reinstates a suspended permit."
    PRD §3.8: "Reinstatement clears `suspended_until_date` and `suspension_reason_code` to null,
    leaves `suspension_count` at its accumulated value, re-derives the compliance signals and
    `compliance_status`, and recomputes the holder's `active_permit_count` and `status`. It does
    **not** restore the guide roster the suspension revoked; the holder must authorize guides
    again from scratch."

    Design: Difficulty/non_linear_state_machine/permit_parallel_dimensions_independent
    """
    context = setup_active_permit()
    permit_id = context["permit"]["id"]
    outfitter_id = context["outfitter"]["id"]

    assert context["permit"]["administrative_status"] == "ACTIVE"
    assert context["permit"]["compliance_status"] == "COMPLIANT"
    assert context["permit"]["authorized_client_capacity_total"] == 12
    assert context["use_area"]["party_size_max"] == 12

    action = issue_noncompliance_action(
        permit_id,
        severity="MODERATE",
        action_type="WARNING",
        cited_provision="operating plan clause 4 - stock containment",
        cure_deadline_date="2027-06-30",
    )
    assert action["points"] == 5
    cited = read_permit(permit_id)
    assert cited["open_noncompliance_points"] == 5
    assert (cited["administrative_status"], cited["compliance_status"]) == (
        "ACTIVE",
        "PROBATION",
    ), "five points move only the compliance dimension"
    assert cited["suspension_count"] == 0

    suspended = validate_success(
        api_client.suspend_permit(
            permit_id,
            {
                "suspension_reason_code": "OFFICER_ORDER",
                "suspended_until_date": "2027-03-05",
            },
            OFFICER,
        )
    )
    assert (suspended["administrative_status"], suspended["compliance_status"]) == (
        "SUSPENDED",
        "PROBATION",
    ), "the administrative hop leaves compliance untouched"
    assert suspended["suspension_reason_code"] == "OFFICER_ORDER"
    assert suspended["suspended_until_date"].startswith("2027-03-05")
    assert suspended["suspension_count"] == 1
    assert suspended["authorized_client_capacity_total"] == 0
    assert read_outfitter(outfitter_id)["status"] == "SUSPENDED"

    cure_action(action["id"], outfitter_id, "Highline relocated and re-inspected")
    cured = read_permit(permit_id)
    assert cured["open_noncompliance_points"] == 0
    assert (cured["administrative_status"], cured["compliance_status"]) == (
        "SUSPENDED",
        "COMPLIANT",
    ), "a single status enum cannot express this pair"

    reinstated = validate_success(api_client.reinstate_permit(permit_id, OFFICER))
    assert (reinstated["administrative_status"], reinstated["compliance_status"]) == (
        "ACTIVE",
        "COMPLIANT",
    )
    assert reinstated["suspension_count"] == 1, "the tally is never decremented"
    assert reinstated["suspended_until_date"] is None
    assert reinstated["suspension_reason_code"] is None
    assert reinstated["authorized_client_capacity_total"] == 0

    rows, meta = list_permit_authorizations(permit_id, params={"status": "AUTHORIZED"})
    assert rows == []
    assert meta["total_count"] == 0, "reinstatement does not rebuild the roster"
    assert read_outfitter(outfitter_id)["status"] == "PERMITTED"


def test_the_compliance_ladder_runs_all_the_way_down_under_a_never_activated_permit():
    """PRD §3.4: "They advance on different triggers and their value sets are disjoint, so a
    permit legitimately carries a pair such as `ACTIVE` with `PROBATION`, or `SUSPENDED` with
    `NONCOMPLIANT`."
    PRD §3.8: "If `open_noncompliance_points` is at or above **12**, the permit is `NONCOMPLIANT`.
    Otherwise, if `open_noncompliance_points` is at or above **5**, or `insurance_current` is
    false, or `fee_delinquent` is true, the permit is on `PROBATION`. Otherwise it is
    `COMPLIANT`."
    PRD §3.8: "Entering `NONCOMPLIANT` while `administrative_status` is `ACTIVE` suspends the
    permit, with `suspension_reason_code` `POINTS_THRESHOLD` and a suspension length of 30 days
    multiplied by one plus the count of that permit's `MAJOR` actions in `UPHELD`"
    PRD §3.8: "An `action_type` of `SUSPENSION`, by contrast, does not suspend anything by itself;
    suspension arrives only through the point threshold or an officer's explicit order."
    PRD §3.8: "Revocation is terminal and reaches from `ISSUED`, `ACTIVE` or `SUSPENDED`."

    Design: Difficulty/non_linear_state_machine/permit_parallel_dimensions_independent
    """
    context = setup_issued_permit()
    permit_id = context["permit"]["id"]
    assert (
        context["permit"]["administrative_status"],
        context["permit"]["compliance_status"],
    ) == ("ISSUED", "COMPLIANT")

    issue_noncompliance_action(
        permit_id,
        severity="MODERATE",
        action_type="WARNING",
        cited_provision="operating plan clause 4 - stock containment",
    )
    on_probation = read_permit(permit_id)
    assert on_probation["open_noncompliance_points"] == 5
    assert (
        on_probation["administrative_status"],
        on_probation["compliance_status"],
    ) == ("ISSUED", "PROBATION")

    issue_noncompliance_action(
        permit_id,
        severity="MAJOR",
        action_type="SUSPENSION",
        cited_provision="36 CFR 261.10(c)",
    )
    breached = read_permit(permit_id)
    assert breached["open_noncompliance_points"] == 15
    assert (breached["administrative_status"], breached["compliance_status"]) == (
        "ISSUED",
        "NONCOMPLIANT",
    ), "the suspension cascade fires only while the permit is ACTIVE"
    assert breached["suspension_count"] == 0
    assert breached["suspended_until_date"] is None
    assert breached["suspension_reason_code"] is None

    validate_error(
        api_client.reinstate_permit(permit_id, OFFICER),
        ApiErrorId.ERR_PERMIT_NOT_OPERATIONAL,
    )

    revoked = validate_success(
        api_client.revoke_permit(
            permit_id, {"revocation_reason_code": "HOLDER_SURRENDER"}, OFFICER
        )
    )
    assert (revoked["administrative_status"], revoked["compliance_status"]) == (
        "REVOKED",
        "NONCOMPLIANT",
    ), "a terminal administrative state does not clear the compliance dimension"
    assert revoked["open_noncompliance_points"] == 15
    assert read_outfitter(context["outfitter"]["id"])["status"] == "APPLICANT"


def test_a_revoked_permit_a_superseded_finding_and_a_dead_authorization_absorb_everything():
    """PRD §3.4: "`administrative_status` answers "may the holder operate" and takes values
    `ISSUED`, `ACTIVE`, `SUSPENDED`, `REVOKED`, `EXPIRED` and `CLOSED`, of which the last three
    are terminal."
    PRD §3.4: "The permit's `administrative_status` must be `ISSUED`, else
    `ERR_PERMIT_NOT_OPERATIONAL` (HTTP 409)"
    PRD §3.6: "Three kinds of evidence hang off a permit, and all three may only be filed while
    the permit's `administrative_status` is `ISSUED` or `ACTIVE`; against a `SUSPENDED`,
    `REVOKED`, `EXPIRED` or `CLOSED` permit the filing is refused with
    `ERR_PERMIT_NOT_OPERATIONAL`."
    PRD §2.5: "A use report filed against a suspended permit that would *also* breach the permit's
    service-day cap returns the state error `ERR_PERMIT_NOT_OPERATIONAL`, never the fiscal
    `ERR_SERVICE_DAY_LIMIT_EXCEEDED`."
    PRD §3.1: "attempting to publish one that is already `PUBLISHED`, or one that has been
    `SUPERSEDED`, returns `ERR_INVALID_ASSESSMENT_STATE`."
    PRD §3.1: "`SUPERSEDED` is terminal: the row keeps its `published_at` and its last computed
    figures forever and is excluded from every later recomputation."
    PRD §3.8: "Revocation releases the committed allocation — the area's `committed_service_days`
    drops by the permit's `authorized_service_days`, and `available_service_days`, `demand_ratio`
    and `allocation_posture` are recomputed, along with the governing assessment's allocation
    figures — revokes every `AUTHORIZED` authorization with reason `PERMIT_CLOSED`"

    Design: Corner/state_machines/terminal_states_refuse_every_further_trigger_and_hold_their_frozen_fields
    """
    context = setup_issued_permit()
    permit_id = context["permit"]["id"]
    outfitter_id = context["outfitter"]["id"]
    area_id = context["use_area"]["id"]
    holder = context["holder_headers"]
    na1 = context["needs_assessment"]

    guide = create_qualified_guide(outfitter_id, **LEAD_WFR_GUIDE)
    authorization = authorize_guide(permit_id, guide["id"], outfitter_id)
    assert authorization["authorized_client_capacity"] == 8
    create_outfitter(**CEDAR)

    create_published_assessment(area_id, determined_capacity_service_days=800)

    revoked = validate_success(
        api_client.revoke_permit(
            permit_id, {"revocation_reason_code": "HOLDER_SURRENDER"}, OFFICER
        )
    )
    assert revoked["administrative_status"] == "REVOKED"
    version_after_revoke = revoked["version"]

    validate_error(
        api_client.revoke_permit(
            permit_id, {"revocation_reason_code": "HOLDER_SURRENDER"}, OFFICER
        ),
        ApiErrorId.ERR_PERMIT_NOT_OPERATIONAL,
    )
    validate_error(
        api_client.activate_permit(permit_id, OFFICER),
        ApiErrorId.ERR_PERMIT_NOT_OPERATIONAL,
    )
    validate_error(
        api_client.create_trip_use_report(
            permit_id,
            trip_use_report_payload(period_end_date="2027-06-15"),
            holder,
        ),
        ApiErrorId.ERR_PERMIT_NOT_OPERATIONAL,
    )
    validate_error(
        api_client.create_insurance_certificate(
            permit_id, insurance_certificate_payload(carrier_name="Cascade Mutual"), holder
        ),
        ApiErrorId.ERR_PERMIT_NOT_OPERATIONAL,
    )
    validate_error(
        api_client.create_guide_authorization(
            permit_id, {"guide_id": guide["id"]}, holder
        ),
        ApiErrorId.ERR_PERMIT_NOT_OPERATIONAL,
    )

    validate_error(
        api_client.revoke_guide_authorization(
            authorization["id"], {"revocation_reason_code": "HOLDER_REQUEST"}, holder
        ),
        ApiErrorId.ERR_AUTHORIZATION_NOT_ACTIVE,
    )

    validate_error(
        api_client.publish_needs_assessment(na1["id"], OFFICER),
        ApiErrorId.ERR_INVALID_ASSESSMENT_STATE,
    )

    summary = read_allocation_summary(area_id)
    assert summary["allocatable_service_days"] == 900
    assert summary["committed_service_days"] == 0
    assert summary["pending_service_days"] == 0
    assert summary["available_service_days"] == 900, (
        "the 200 committed days were released exactly once despite the second revoke"
    )
    assert summary["demand_ratio"] == 0.0
    assert summary["allocation_posture"] == "OPEN"

    assert read_permit(permit_id)["version"] == version_after_revoke, (
        "none of the refused calls advanced the target's version"
    )

    rows, meta = list_permit_authorizations(permit_id)
    assert meta["total_count"] == 1
    assert rows[0]["status"] == "REVOKED"
    assert rows[0]["revocation_reason_code"] == "PERMIT_CLOSED"
    assert rows[0]["authorized_client_capacity"] == 8, (
        "the frozen audit figure survives the revocation"
    )
    assert read_permit(permit_id)["authorized_client_capacity_total"] == 0

    assessments, _meta = read_needs_assessment_list(
        area_id, params={"assessment_year": 2027}
    )
    by_id = {row["id"]: row for row in assessments}
    assert by_id[na1["id"]]["status"] == "SUPERSEDED"
    assert by_id[na1["id"]]["published_at"] is not None
