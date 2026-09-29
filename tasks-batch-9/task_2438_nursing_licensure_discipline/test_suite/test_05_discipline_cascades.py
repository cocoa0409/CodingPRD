"""Multi-level cascades: a revocation order and a broken monitoring agreement."""
from test_helpers import (
    COORDINATOR,
    FIVE_MEMBER_PANEL,
    PRESIDING,
    ApiClient,
    assert_license_dimensions,
    assert_reports_match,
    cast_votes,
    complete_evidence,
    dispose_complaint,
    record_hearing_event,
    reread_agreement,
    reread_complaint,
    reread_license,
    reread_nurse,
    reports_for_source,
    seed_active_agreement,
    seed_active_license,
    seed_aprn_license,
    seed_investigated_complaint,
    seed_proceeding,
    seed_produced_evidence_request,
    validate_success,
)


def _revocation_ready_proceeding(api: ApiClient):
    """A registered-nurse credential with a dependent advanced-practice credential,
    carried through a unanimous revocation vote on a criminal-conduct complaint."""
    ctx = seed_active_license(
        api,
        program_overrides={
            "program_code": "OH-BSN-41",
            "program_name": "Erie BSN",
            "degree_level": "BSN",
            "nclex_first_time_pass_rate_bp": 8900,
        },
        nurse_overrides={"full_name": "Rosa Kingsley", "birth_year": 1981,
                         "ssn_last4": "6620"},
    )
    ctx = seed_aprn_license(
        api, ctx,
        program_overrides={
            "program_code": "OH-MSN-41",
            "program_name": "Erie MSN",
            "degree_level": "MSN",
            "nclex_first_time_pass_rate_bp": 9400,
        },
        aprn_role="NP",
    )
    complaint = seed_investigated_complaint(
        api, ctx["license_id"],
        complainant_type="OTHER_STATE_BOARD",
        violation_category="CRIMINAL_CONDUCT",
        incident_date="2026-06-20T00:00:00Z",
        allegation_codes=["CRM-DIV"],
        employer_custodian_codes=["MERCY-GEN"],
    )
    seed_produced_evidence_request(
        api, complaint["id"], page_count=310,
        record_class="PHARMACY_DISPENSING",
        custodian_code="MERCY-GEN",
        phi_authorization_id="PHI-AUTH-6620",
        hold_start_at="2026-08-04T00:00:00Z",
        hold_end_at="2026-09-04T00:00:00Z",
    )
    complete_evidence(api, complaint["id"])
    dispose_complaint(api, complaint["id"], "REFER_TO_PROCEEDING")
    proceeding = seed_proceeding(api, complaint["id"], FIVE_MEMBER_PANEL,
                                hearing_date="2026-09-15T00:00:00Z",
                                notice_period_days=30)
    record_hearing_event(api, proceeding["id"], "CONVENE")
    cast_votes(api, proceeding["id"],
               [(member, "REVOCATION") for member in FIVE_MEMBER_PANEL])
    ctx["proceeding"] = record_hearing_event(api, proceeding["id"], "CLOSE_HEARING")
    ctx["proceeding_id"] = proceeding["id"]
    ctx["complaint_id"] = complaint["id"]
    return ctx


def test_revocation_order_drags_the_dependent_aprn_credential_down_with_it(
    api: ApiClient,
):
    """PRD §3.8: "`REVOCATION` runs the widest cascade in the system, permitted
    from `INVESTIGATION_PENDING`, `RESTRICTED`, or `SUSPENDED`: this credential's
    `encumbrance_status` becomes `REVOKED` and its `license_status` becomes
    `SURRENDERED`; its `multistate_privilege_status` becomes `PRIVILEGE_REVOKED`;
    every other credential of the same nurse whose `base_license_id` equals this
    credential's identifier is dragged down with it, moving to `license_status`
    `SURRENDERED`, `encumbrance_status` `REVOKED`, and
    `multistate_privilege_status` `PRIVILEGE_REVOKED`, so revoking a
    registered-nurse credential necessarily revokes the advanced-practice
    credential built on it; every monitoring agreement of the nurse standing at
    `OFFERED`, `EXECUTED`, `ACTIVE`, or `SUSPENDED_PENDING_REVIEW` moves to
    `TERMINATED`; and the nurse's aggregate `status` becomes `REVOKED` once every
    credential of that nurse carries `encumbrance_status` `REVOKED`."

    PRD §3.8: "Issuing the order moves the proceeding to the terminal
    `ORDER_ISSUED`, stamps `order_issued_at` from the logical clock, stores the
    supplied `ordered_restriction_codes`, moves the complaint from
    `PROCEEDING_OPENED` to the terminal `CLOSED` **without** returning the
    encumbrance to `CLEAR` — a disciplined credential stays encumbered —
    recomputes `open_encumbrance_count`, and recomputes the nurse's
    `prior_discipline_count`, which now counts this order."

    Design: Difficulty/transitive_cascade/revocation_order_cascades_through_dependent_aprn_to_reports
    """
    ctx = _revocation_ready_proceeding(api)
    assert ctx["proceeding"]["adopted_sanction_tier"] == "REVOCATION"
    assert ctx["proceeding"]["sanction_floor_tier"] == "SUSPENSION", (
        "A criminal-conduct base of 5 with produced pharmacy records nets zero, "
        f"so the floor is index 5; got {ctx['proceeding']['sanction_floor_tier']}"
    )

    ordered = validate_success(
        api.issue_order(ctx["proceeding_id"], PRESIDING,
                        {"ordered_restriction_codes": []})
    )

    assert ordered["status"] == "ORDER_ISSUED"
    registered_nurse = reread_license(api, ctx["license_id"])
    assert_license_dimensions(registered_nurse, "SURRENDERED", "REVOKED")
    assert registered_nurse["multistate_privilege_status"] == "PRIVILEGE_REVOKED"

    advanced_practice = reread_license(api, ctx["aprn_license_id"])
    assert_license_dimensions(advanced_practice, "SURRENDERED", "REVOKED")
    assert advanced_practice["multistate_privilege_status"] == "PRIVILEGE_REVOKED", (
        "The dependent credential is dragged down because its base_license_id "
        "pointed at the revoked credential"
    )
    assert reread_complaint(api, ctx["complaint_id"])["status"] == "CLOSED"


def test_revocation_order_queues_two_national_reports_and_one_interstate_report(
    api: ApiClient,
):
    """PRD §3.8: "One notification report is queued per credential the order
    encumbers, on the `NPDB` channel — or on the `NURSE_AIDE_REGISTRY` channel
    for a `NURSE_AIDE` credential — with `source_entity_type`
    `DISCIPLINARY_PROCEEDING`, `report_kind` `INITIAL`, and `basis_code` equal to
    the adopted tier, plus **exactly one** report on the `INTERSTATE_COMPACT`
    channel with `basis_code` `PRIVILEGE_LOSS` regardless of how many credentials
    were touched."

    PRD §3.8: "A revocation that drags down one dependent credential therefore
    produces two national reports and one interstate report, not two of each."

    PRD §2.7: "The derived posture follows from the count, but only when no board
    order is in force: if the credential's `encumbrance_status` is not one of
    `RESTRICTED`, `SUSPENDED`, or `REVOKED`, then it becomes `CLEAR` when the
    recomputed `open_encumbrance_count` is zero and `INVESTIGATION_PENDING`
    otherwise."

    PRD §3.1: "`prior_discipline_count` starts at 0 and equals the number of
    disciplinary proceedings against that nurse that reached `ORDER_ISSUED` with
    an adopted sanction other than `NONE`."

    Design: Difficulty/transitive_cascade/revocation_order_cascades_through_dependent_aprn_to_reports
    """
    ctx = _revocation_ready_proceeding(api)

    validate_success(
        api.issue_order(ctx["proceeding_id"], PRESIDING,
                        {"ordered_restriction_codes": []})
    )

    credential = reread_license(api, ctx["license_id"])
    assert credential["open_encumbrance_count"] == 0, (
        f"The complaint closed, so the count is 0; got {credential['open_encumbrance_count']}"
    )
    assert credential["encumbrance_status"] == "REVOKED", (
        "A board order in force is never returned to CLEAR by the arithmetic"
    )
    nurse = reread_nurse(api, ctx["nurse_id"])
    assert nurse["prior_discipline_count"] == 1, (
        f"One order issued with a sanction other than NONE, got "
        f"{nurse['prior_discipline_count']}"
    )
    assert nurse["status"] == "REVOKED", (
        f"Every credential of this nurse is REVOKED, got {nurse['status']}"
    )

    reports = reports_for_source(api, ctx["proceeding_id"])
    assert len(reports) == 3, (
        f"Two credentials encumbered plus one interstate report is 3, got {len(reports)}"
    )
    national = assert_reports_match(reports, "NPDB", "REVOCATION", 2)
    interstate = assert_reports_match(reports, "INTERSTATE_COMPACT", "PRIVILEGE_LOSS", 1)
    for report in national + interstate:
        assert report["status"] == "QUEUED", (
            f"A newly queued report holds status QUEUED, got {report['status']}"
        )
        assert report["source_entity_type"] == "DISCIPLINARY_PROCEEDING"


def _active_monitoring_agreement(api: ApiClient):
    """A signed, active alternative-to-discipline agreement on a self-reported
    substance-use complaint."""
    return seed_active_agreement(
        api,
        activation_clock="2026-09-01T00:00:00Z",
        program_overrides={
            "program_code": "OH-BSN-51",
            "program_name": "Sandusky BSN",
            "degree_level": "BSN",
            "nclex_first_time_pass_rate_bp": 8600,
        },
        nurse_overrides={"full_name": "Theo Nakamura", "birth_year": 1994,
                         "ssn_last4": "2255"},
        complaint_overrides={
            "complainant_type": "SELF_REPORT",
            "violation_category": "SUBSTANCE_USE",
            "incident_date": "2026-07-18T00:00:00Z",
            "employer_custodian_codes": ["MERCY-GEN"],
            "page_count": 24,
            "evidence_overrides": {
                "record_class": "EMPLOYER_PERSONNEL",
                "custodian_code": "MERCY-GEN",
                "hold_start_at": "2026-08-02T00:00:00Z",
                "hold_end_at": "2026-08-25T00:00:00Z",
            },
        },
        start_date="2026-09-01T00:00:00Z",
        end_date="2027-09-01T00:00:00Z",
        narcotic_access_restricted=True,
        required_screens_per_quarter=4,
    )


def test_breach_suspends_encumbrance_while_registration_stays_active(api: ApiClient):
    """PRD §3.7: "A `BREACH` is the loud counterpart, may be declared from either
    `ACTIVE` or `SUSPENDED_PENDING_REVIEW`, and runs an identical four-link
    cascade from both."

    PRD §3.7: "Link one moves the agreement to the terminal `BREACHED`."

    PRD §3.7: "Link two moves the linked complaint from `ATD_ACTIVE` to
    `PROCEEDING_OPENED` — the diversion has failed and the matter becomes
    contested."

    PRD §3.7: "Link three moves the credential's `encumbrance_status` to
    `SUSPENDED`, permitted from `INVESTIGATION_PENDING` or `RESTRICTED`."

    Design: Difficulty/transitive_cascade/atd_breach_cascades_from_agreement_to_npdb_report
    """
    ctx = _active_monitoring_agreement(api)
    assert ctx["agreement"]["status"] == "ACTIVE", (
        f"The clock reached the start date, got {ctx['agreement']['status']}"
    )

    breached = validate_success(
        api.record_monitoring_event(
            ctx["agreement_id"],
            {"event_type": "BREACH",
             "note": "positive screen and worksite non-compliance"},
            COORDINATOR,
        )
    )

    assert breached["status"] == "BREACHED"
    assert reread_complaint(api, ctx["complaint_id"])["status"] == "PROCEEDING_OPENED"
    credential = reread_license(api, ctx["license_id"])
    assert_license_dimensions(credential, "ACTIVE", "SUSPENDED")
    assert credential["open_encumbrance_count"] == 1, (
        f"The complaint is still in the open set, got {credential['open_encumbrance_count']}"
    )


def test_breach_queues_exactly_one_npdb_report_against_the_agreement(api: ApiClient):
    """PRD §3.7: "Link four sets the credential's `multistate_privilege_status` to
    `PRIVILEGE_REVOKED` and queues a notification report on the `NPDB` channel
    with `source_entity_type` `MONITORING_AGREEMENT`, `report_kind` `INITIAL`,
    `basis_code` `ATD_BREACH`, and `status` `QUEUED`; the nurse's aggregate
    `status` is set to `ENCUMBERED`."

    PRD §3.1: "`atd_participation_count` starts at 0 and equals the number of
    monitoring agreements for that nurse whose status has ever reached
    `EXECUTED` — note the "ever": completing or breaching an agreement does not
    decrement it."

    PRD §3.1: "`prior_discipline_count` starts at 0 and equals the number of
    disciplinary proceedings against that nurse that reached `ORDER_ISSUED` with
    an adopted sanction other than `NONE`."

    Design: Difficulty/transitive_cascade/atd_breach_cascades_from_agreement_to_npdb_report
    """
    ctx = _active_monitoring_agreement(api)

    validate_success(
        api.record_monitoring_event(
            ctx["agreement_id"],
            {"event_type": "BREACH",
             "note": "positive screen and worksite non-compliance"},
            COORDINATOR,
        )
    )

    credential = reread_license(api, ctx["license_id"])
    assert credential["multistate_privilege_status"] == "PRIVILEGE_REVOKED"
    nurse = reread_nurse(api, ctx["nurse_id"])
    assert nurse["status"] == "ENCUMBERED"
    assert nurse["atd_participation_count"] == 1, (
        f"One agreement ever reached EXECUTED, got {nurse['atd_participation_count']}"
    )
    assert nurse["prior_discipline_count"] == 0, (
        "A breach is not a disciplinary order, so the discipline count stays 0"
    )

    reports = reports_for_source(api, ctx["agreement_id"])
    matched = assert_reports_match(reports, "NPDB", "ATD_BREACH", 1)
    assert matched[0]["source_entity_type"] == "MONITORING_AGREEMENT"
    assert matched[0]["report_kind"] == "INITIAL"
    assert matched[0]["status"] == "QUEUED"
    assert matched[0]["subject_nurse_id"] == ctx["nurse_id"]
    assert reread_agreement(api, ctx["agreement_id"])["status"] == "BREACHED"
