"""Endpoint corners: what each route answers at the edges of its contract — computed reads,
empty collections, pagination limits, payload-shape refusals and unresolvable path segments."""
from datetime import datetime

from test_helpers import (
    ApiErrorId,
    api_client,
    add_draft_revision,
    create_cycle,
    create_partner,
    create_skill_profile,
    create_vetted_volunteer,
    create_volunteer,
    deliverable_payload,
    handoff_payload,
    make_partner_contact_headers,
    make_program_manager_headers,
    make_volunteer_headers,
    milestone_payload,
    partner_org_payload,
    program_cycle_payload,
    project_request_payload,
    read_cycle,
    read_engagement,
    read_offer,
    read_request,
    read_window,
    satisfaction_survey_payload,
    scope_definition_payload,
    set_clock,
    setup_accepted_engagement,
    setup_draft_request,
    setup_engagement,
    setup_handed_off_engagement,
    setup_in_progress_engagement,
    setup_offer,
    setup_scoped_request,
    setup_scoping_request,
    time_log_payload,
    validate_error,
    validate_paginated,
    validate_success,
    volunteer_payload,
)

NONEXISTENT_ID = "00000000-0000-4000-8000-000000000000"

MID_BUDGET = 3000000.00


def _instant(value):
    """Parse an ISO 8601 UTC stamp into a comparable datetime.

    The PRD fixes the instants a stamp must carry but not the number of fractional
    digits it is rendered with, so comparisons are made on parsed instants.
    """
    assert isinstance(value, str) and value, f"expected an ISO 8601 timestamp, got {value!r}"
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


# ---------------------------------------------------------------------------
# Computed and companion reads
# ---------------------------------------------------------------------------
def test_01_partner_summary_read_reflects_one_open_engagement(api):
    """PRD §3.1: "A dedicated computed read on the partner exposes `capacity_class`,
    `max_concurrent_engagements`, `open_engagement_count`, `satisfaction_index`,
    `satisfaction_sample_size` and the per-survey `composite_score` figures that produced the
    index, which is the fastest way for program staff to see why a partner sits where it does."
    PRD §3.1: "The engagement count is a live figure, not a stored tally: it counts the partner's
    engagements whose `work_status` is `NOT_STARTED`, `IN_PROGRESS`, `SUBMITTED` or `ACCEPTED`."
    PRD §3.9: "With no qualifying survey the `satisfaction_index` is null."

    Design: Corner/endpoints/endpoint_partner_summary_computed_read_reflects_open_engagement_count
    """
    world = setup_engagement(partner_budget=MID_BUDGET, cycle_slots=4)

    summary = validate_success(
        api_client.get_partner_org_summary(world["partner"]["id"], world["pm_headers"])
    )

    assert summary["capacity_class"] == "MID", (
        f"Expected capacity_class MID for a 3000000.00 budget, got {summary['capacity_class']}"
    )
    assert summary["max_concurrent_engagements"] == 4, (
        f"Expected an engagement ceiling of 4 for a MID partner, got "
        f"{summary['max_concurrent_engagements']}"
    )
    assert summary["open_engagement_count"] == 1, (
        f"The one NOT_STARTED engagement must count as open, got "
        f"{summary['open_engagement_count']}"
    )
    assert summary["satisfaction_index"] is None, (
        f"Expected a null satisfaction_index with no survey filed, got "
        f"{summary['satisfaction_index']}"
    )
    assert summary["satisfaction_sample_size"] == 0, (
        f"Expected satisfaction_sample_size 0 with no survey filed, got "
        f"{summary['satisfaction_sample_size']}"
    )


def test_02_cycle_engagement_list_keeps_a_terminated_row_after_the_slot_is_released(api):
    """PRD §4 `GET /program-cycles/{id}/engagements`: "Every engagement occupying a slot in this
    cycle, including terminal ones."
    PRD §3.9: "The cycle's `slots_committed` falls by one and the posture recomputes."
    PRD §3.1: "`posture` is `OPEN` while utilization is below 0.8000, `RESTRICTED` from 0.8000 up
    to but not including 1.0000, and `FROZEN` at 1.0000 and above; both band floors are inclusive,
    so a utilization of exactly 0.8000 is `RESTRICTED` and exactly 1.0000 is `FROZEN`."

    Design: Corner/endpoints/endpoint_cycle_engagements_lists_terminal_rows_after_slot_release
    """
    world = setup_in_progress_engagement(cycle_slots=4)

    terminated = validate_success(
        api_client.terminate_engagement(
            world["engagement"]["id"], world["pm_headers"], {"termination_reason": "ADMIN"}
        )
    )
    assert terminated["work_status"] == "TERMINATED", (
        f"Expected work_status TERMINATED after termination, got {terminated['work_status']}"
    )

    rows, meta = validate_paginated(
        api_client.list_cycle_engagements(world["cycle"]["id"], world["pm_headers"])
    )

    assert meta["total_count"] == 1, (
        f"The terminated engagement must still be listed for the cycle, got total_count "
        f"{meta['total_count']}"
    )
    assert [row["id"] for row in rows] == [world["engagement"]["id"]], (
        f"Expected the cycle listing to carry the one engagement, got "
        f"{[row['id'] for row in rows]}"
    )
    assert rows[0]["work_status"] == "TERMINATED", (
        f"Expected the listed row to read TERMINATED, got {rows[0]['work_status']}"
    )

    cycle = read_cycle(world)
    assert cycle["slots_committed"] == 0, (
        f"Termination must drop slots_committed back to 0, got {cycle['slots_committed']}"
    )
    assert cycle["slots_reserved"] == 0, (
        f"Expected slots_reserved 0 after acceptance and termination, got "
        f"{cycle['slots_reserved']}"
    )
    assert cycle["slots_available"] == 4, (
        f"Expected all 4 slots available again, got {cycle['slots_available']}"
    )
    assert float(cycle["utilization_ratio"]) == 0.0000, (
        f"Expected utilization_ratio 0.0000 once the slot is released, got "
        f"{cycle['utilization_ratio']}"
    )
    assert cycle["posture"] == "OPEN", (
        f"Expected posture OPEN at 0.0000 utilization, got {cycle['posture']}"
    )


def test_03_milestone_time_log_listing_is_partitioned_by_the_approving_hold(api):
    """PRD §4 `GET /milestones/{id}/time-logs`: "Time logs approved by one milestone hold."
    PRD §3.7: "The hold moves the milestone `SCHEDULED → HELD` with `held_at` stamped, and then,
    in this order: every child time log of the engagement that is still unapproved and whose
    `work_date` is at or before the milestone's `due_at` flips `approved` to true with
    `approved_at` stamped and its `milestone_id` set to this milestone; the engagement's
    `approved_hours` is recomputed; the creep calculation reruns and may move
    `creep_escalation_level`; `variance_hours` is computed as the reported cumulative hours less
    the engagement's `approved_hours` *measured after those approvals*, which is why an early hold
    can show a negative variance; and `escalation_raised` is set to true when the recomputed
    `creep_escalation_level` is `ESCALATED` or `BREACH`."

    Design: Corner/endpoints/endpoint_milestone_time_logs_partitioned_by_approving_hold
    """
    world = setup_in_progress_engagement()
    engagement_id = world["engagement"]["id"]
    pm = world["pm_headers"]
    volunteer = world["volunteer_headers"]

    for hours in (12.00, 12.00, 8.00, 8.00):
        validate_success(
            api_client.create_time_log(
                engagement_id,
                time_log_payload(work_date="2026-08-01T09:00:00Z", hours=hours),
                volunteer,
            ),
            201,
        )

    first = validate_success(
        api_client.create_milestone(
            engagement_id, milestone_payload(due_at="2026-08-02T00:00:00Z"), pm
        ),
        201,
    )
    set_clock("2026-08-01T12:00:00Z", pm)
    validate_success(
        api_client.hold_milestone(first["id"], {"reported_cumulative_hours": 40.00}, pm)
    )

    validate_success(
        api_client.create_time_log(
            engagement_id,
            time_log_payload(
                work_date="2026-08-01T18:00:00Z", hours=4.00, activity_class="ADMIN"
            ),
            volunteer,
        ),
        201,
    )
    second = validate_success(
        api_client.create_milestone(
            engagement_id, milestone_payload(due_at="2026-08-06T00:00:00Z"), pm
        ),
        201,
    )
    set_clock("2026-08-05T12:00:00Z", pm)
    validate_success(
        api_client.hold_milestone(second["id"], {"reported_cumulative_hours": 44.00}, pm)
    )

    first_rows, first_meta = validate_paginated(
        api_client.list_milestone_time_logs(first["id"], pm)
    )
    assert first_meta["total_count"] == 4, (
        f"Expected the first hold to own its 4 approved logs, got total_count "
        f"{first_meta['total_count']}"
    )
    assert sorted(float(row["hours"]) for row in first_rows) == [8.00, 8.00, 12.00, 12.00], (
        f"Expected hours 8/8/12/12 under the first hold, got "
        f"{[row['hours'] for row in first_rows]}"
    )
    for row in first_rows:
        assert row["approved"] is True, (
            f"A log approved by a hold must read approved true, got {row['approved']}"
        )
        assert row["milestone_id"] == first["id"], (
            f"Expected milestone_id {first['id']} on the approved log, got {row['milestone_id']}"
        )

    second_rows, second_meta = validate_paginated(
        api_client.list_milestone_time_logs(second["id"], pm)
    )
    assert second_meta["total_count"] == 1, (
        f"Expected exactly the one later log under the second hold, got total_count "
        f"{second_meta['total_count']}"
    )
    assert float(second_rows[0]["hours"]) == 4.00, (
        f"Expected the 4.00-hour log under the second hold, got {second_rows[0]['hours']}"
    )
    assert second_rows[0]["milestone_id"] == second["id"], (
        f"Expected milestone_id {second['id']} on the later log, got "
        f"{second_rows[0]['milestone_id']}"
    )

    engagement = read_engagement(world)
    assert float(engagement["approved_hours"]) == 44.00, (
        f"Expected approved_hours 44.00 across both holds, got {engagement['approved_hours']}"
    )


def test_04_scope_revision_listing_shows_the_withdrawn_sibling_draft(api):
    """PRD §3.3: "Any sibling revision still sitting in `DRAFT` moves to `WITHDRAWN` at once, and
    the parent request's `version` advances by one."
    PRD §2.3: "Project requests may be narrowed by `partner_org_id`, `cycle_id` and `status`;
    scope revisions by `project_request_id`, `supersedes_scope_id` and `status`"
    PRD §3.3: "That field reads 0 whenever no revision of the request is `APPROVED`."

    Design: Corner/endpoints/endpoint_scope_definitions_list_filter_shows_withdrawn_draft_revision
    """
    world = setup_scoping_request()

    second = add_draft_revision(world, estimated_hours=50.00, complexity_factor=1.10)

    rows, meta = validate_paginated(
        api_client.list_scope_definitions(
            world["pm_headers"], params={"project_request_id": world["request"]["id"]}
        )
    )
    assert meta["total_count"] == 2, (
        f"Expected both revisions to remain listed, got total_count {meta['total_count']}"
    )
    assert meta["has_more"] is False, (
        f"Expected has_more false for a two-row page, got {meta['has_more']}"
    )
    by_revision = {row["revision_no"]: row for row in rows}
    assert by_revision[1]["status"] == "WITHDRAWN", (
        f"Expected revision 1 to read WITHDRAWN, got {by_revision[1]['status']}"
    )
    assert by_revision[2]["status"] == "DRAFT", (
        f"Expected revision 2 to read DRAFT, got {by_revision[2]['status']}"
    )
    assert by_revision[2]["id"] == second["id"], (
        f"Expected revision 2 to be the new row {second['id']}, got {by_revision[2]['id']}"
    )
    assert float(by_revision[2]["estimated_hours"]) == 50.00, (
        f"Expected estimated_hours 50.00 on the new revision, got "
        f"{by_revision[2]['estimated_hours']}"
    )
    assert float(by_revision[2]["complexity_factor"]) == 1.10, (
        f"Expected complexity_factor 1.10 on the new revision, got "
        f"{by_revision[2]['complexity_factor']}"
    )

    draft_rows, draft_meta = validate_paginated(
        api_client.list_scope_definitions(
            world["pm_headers"],
            params={"project_request_id": world["request"]["id"], "status": "DRAFT"},
        )
    )
    assert draft_meta["total_count"] == 1, (
        f"Expected the conjunctive DRAFT filter to return one row, got total_count "
        f"{draft_meta['total_count']}"
    )
    assert draft_rows[0]["id"] == second["id"], (
        f"Expected the DRAFT filter to return {second['id']}, got {draft_rows[0]['id']}"
    )

    request = read_request(world)
    assert request["status"] == "SCOPING", (
        f"Expected the request to stay in SCOPING, got {request['status']}"
    )
    assert request["active_scope_revision_no"] == 0, (
        f"Expected active_scope_revision_no 0 while no revision is APPROVED, got "
        f"{request['active_scope_revision_no']}"
    )


def test_05_advancing_the_clock_alone_leaves_an_expired_window_offer_untouched(api):
    """PRD §2.5: "Advancing the clock performs no sweep of its own — expired offers and overdue
    check-ins are only acted upon when a cycle recalculation runs, as described in §3.1."
    PRD §3.4: "Its `reserved_hours` is the required-hours figure computed above, its `offered_at`
    is the logical clock, and its `expires_at` is `offered_at` plus a time-to-live chosen by the
    request's `urgency`: five days for a `ROUTINE` request, three days for an `ELEVATED` one, and
    a single day for a `CRITICAL` one."
    PRD §3.4: "`responded_at`, `decline_reason` and `withdraw_reason` all start null."

    Design: Corner/endpoints/endpoint_clock_advance_alone_performs_no_expiry_sweep
    """
    world = setup_offer(cycle_slots=4)

    set_clock("2026-08-04T00:00:00Z", world["pm_headers"])

    offer = read_offer(world)
    assert offer["status"] == "OFFERED", (
        f"A clock advance must not sweep the offer, got status {offer['status']}"
    )
    assert offer["responded_at"] is None, (
        f"Expected a null responded_at on an untouched offer, got {offer['responded_at']}"
    )
    assert _instant(offer["expires_at"]) == _instant("2026-08-06T00:00:00Z"), (
        f"Expected a five-day ROUTINE expiry at 2026-08-06T00:00:00Z, got {offer['expires_at']}"
    )
    assert float(offer["reserved_hours"]) == 40.00, (
        f"Expected reserved_hours 40.00 for 40 estimated hours at factor 1.00, got "
        f"{offer['reserved_hours']}"
    )

    request = read_request(world)
    assert request["status"] == "MATCHING", (
        f"Expected the request to stay in MATCHING, got {request['status']}"
    )
    assert request["failed_match_rounds"] == 0, (
        f"No sweep ran, so failed_match_rounds must stay 0, got {request['failed_match_rounds']}"
    )

    cycle = read_cycle(world)
    assert cycle["slots_reserved"] == 1, (
        f"Expected the reserved slot to persist, got slots_reserved {cycle['slots_reserved']}"
    )
    assert cycle["slots_committed"] == 0, (
        f"Expected slots_committed 0 while the offer is unanswered, got "
        f"{cycle['slots_committed']}"
    )
    assert float(cycle["utilization_ratio"]) == 0.2500, (
        f"Expected utilization_ratio 0.2500 for one reserved slot of four, got "
        f"{cycle['utilization_ratio']}"
    )

    window = read_window(world)
    assert float(window["hours_committed"]) == 40.00, (
        f"Expected the window to keep its 40.00 committed hours, got "
        f"{window['hours_committed']}"
    )


def test_06_restricted_tier_handoff_without_a_destruction_certificate_is_refused(api):
    """PRD §3.8: "It requires the engagement to be in `ACCEPTED`, and the payload carries
    `confidentiality_attested`, which must be true, a `handoff_artifact_count` of at least one
    naming how many artifacts were transferred, and — when the pinned revision's
    `confidentiality_tier` is `RESTRICTED` — a non-empty `destruction_certificate_ref`."
    PRD §3.8: "A missing attestation or a missing certificate on a restricted-tier handoff is
    refused with `ERR_CONFIDENTIALITY_ATTESTATION_MISSING`."
    PRD §3.8: "On success `handoff_at` is stamped from the logical clock and the engagement moves
    `ACCEPTED → HANDED_OFF`; the parent request moves `IN_DELIVERY → CLOSED` with `closed_at`
    stamped"

    Design: Corner/endpoints/endpoint_restricted_tier_handoff_without_destruction_certificate_rejected
    """
    world = setup_accepted_engagement(confidentiality_tier="RESTRICTED")

    response = api_client.handoff_engagement(
        world["engagement"]["id"],
        handoff_payload(confidentiality_attested=True, handoff_artifact_count=3),
        world["pm_headers"],
    )
    validate_error(
        response, ApiErrorId.ERR_CONFIDENTIALITY_ATTESTATION_MISSING, expected_status=422
    )

    engagement = read_engagement(world)
    assert engagement["work_status"] == "ACCEPTED", (
        f"The refused handoff must leave the engagement in ACCEPTED, got "
        f"{engagement['work_status']}"
    )
    assert engagement["handoff_at"] is None, (
        f"Expected a null handoff_at after the refusal, got {engagement['handoff_at']}"
    )
    request = read_request(world)
    assert request["status"] == "IN_DELIVERY", (
        f"Expected the parent request to stay IN_DELIVERY, got {request['status']}"
    )

    handed_off = validate_success(
        api_client.handoff_engagement(
            world["engagement"]["id"],
            handoff_payload(
                confidentiality_attested=True,
                handoff_artifact_count=3,
                destruction_certificate_ref="DESTRUCT-2026-0001",
            ),
            world["pm_headers"],
        )
    )
    assert handed_off["work_status"] == "HANDED_OFF", (
        f"Expected HANDED_OFF once the certificate is supplied, got "
        f"{handed_off['work_status']}"
    )


def test_07_a_survey_is_reachable_from_both_its_engagement_and_its_partner(api):
    """PRD §3.9: "Its `composite_score` is a weighted 0-to-100 figure: 0.40 times
    `score_expertise`, plus 0.35 times `score_deliverable_fit`, plus 0.25 times
    `score_responsiveness`, that sum multiplied by 20 and rounded to two decimals."
    PRD §3.9: "The partner's `satisfaction_sample_size` is the number of rows actually used, so it
    ranges from 0 to 5."
    PRD §4 `GET /partner-orgs/{id}/satisfaction-surveys`: "Every satisfaction survey attributed to
    this partner, newest submission first, with the counted-in-index flags."
    PRD §3.9: "Both evaluations run at the end of survey submission, and neither fires below a
    sample size of 3."

    Design: Corner/endpoints/endpoint_satisfaction_survey_links_to_engagement_and_partner
    """
    world = setup_handed_off_engagement(partner_budget=MID_BUDGET)

    survey = validate_success(
        api_client.create_satisfaction_survey(
            world["engagement"]["id"],
            satisfaction_survey_payload(
                score_expertise=5, score_deliverable_fit=4, score_responsiveness=3
            ),
            world["partner_headers"],
        ),
        201,
    )
    assert float(survey["composite_score"]) == 83.00, (
        f"Expected composite_score 83.00 from (0.40*5 + 0.35*4 + 0.25*3) * 20, got "
        f"{survey['composite_score']}"
    )
    assert survey["counted_in_index"] is True, (
        f"A survey of a HANDED_OFF engagement must count in the index, got "
        f"{survey['counted_in_index']}"
    )

    engagement_rows, engagement_meta = validate_paginated(
        api_client.list_engagement_satisfaction_surveys(
            world["engagement"]["id"], world["pm_headers"]
        )
    )
    assert engagement_meta["total_count"] == 1, (
        f"Expected one survey under the engagement, got total_count "
        f"{engagement_meta['total_count']}"
    )
    assert engagement_rows[0]["id"] == survey["id"], (
        f"Expected the engagement listing to carry {survey['id']}, got "
        f"{engagement_rows[0]['id']}"
    )

    partner_rows, partner_meta = validate_paginated(
        api_client.list_partner_org_satisfaction_surveys(
            world["partner"]["id"], world["pm_headers"]
        )
    )
    assert partner_meta["total_count"] == 1, (
        f"Expected one survey attributed to the partner, got total_count "
        f"{partner_meta['total_count']}"
    )
    assert partner_rows[0]["id"] == survey["id"], (
        f"Expected the partner listing to carry {survey['id']}, got {partner_rows[0]['id']}"
    )

    summary = validate_success(
        api_client.get_partner_org_summary(world["partner"]["id"], world["pm_headers"])
    )
    assert float(summary["satisfaction_index"]) == 83.00, (
        f"A single counted survey must set the index to its own composite 83.00, got "
        f"{summary['satisfaction_index']}"
    )
    assert summary["satisfaction_sample_size"] == 1, (
        f"Expected satisfaction_sample_size 1, got {summary['satisfaction_sample_size']}"
    )

    partner = validate_success(
        api_client.get_partner_org(world["partner"]["id"], world["pm_headers"])
    )
    assert partner["status"] == "ACTIVE", (
        f"Standing must not move below a sample size of 3, got status {partner['status']}"
    )


# ---------------------------------------------------------------------------
# Partner org endpoints
# ---------------------------------------------------------------------------
def test_08_enrolling_a_partner_without_a_contact_email_is_refused(api):
    """PRD §3.1: "A `ProgramManager` enrols a nonprofit partner by supplying its legal `name`
    (1 to 160 characters, required), a `contact_email` that must be unique across all partners, a
    mission `sector` drawn from `HEALTH`, `EDUCATION`, `HOUSING`, `ENVIRONMENT`, `ARTS` and
    `CIVIC`, and a self-reported `annual_budget_usd` of at least zero carried to two decimals."
    PRD §2.12: "The request body conforms to the endpoint's input schema — all required fields
    present, enum values inside their declared sets, numbers inside their declared ranges,
    datetimes ISO 8601 UTC — on every write endpoint, otherwise `ERR_VALIDATION` (422)."

    Design: Corner/endpoints/endpoint_create_partner_org_missing_contact_email_rejected
    """
    payload = partner_org_payload()
    payload.pop("contact_email")

    response = api_client.create_partner_org(payload, make_program_manager_headers())

    validate_error(response, ApiErrorId.ERR_VALIDATION, expected_status=422)


def test_09_enrolling_a_partner_in_an_undeclared_sector_is_refused(api):
    """PRD §3.1: "A `ProgramManager` enrols a nonprofit partner by supplying its legal `name`
    (1 to 160 characters, required), a `contact_email` that must be unique across all partners, a
    mission `sector` drawn from `HEALTH`, `EDUCATION`, `HOUSING`, `ENVIRONMENT`, `ARTS` and
    `CIVIC`, and a self-reported `annual_budget_usd` of at least zero carried to two decimals."
    PRD §2.12: "The request body conforms to the endpoint's input schema — all required fields
    present, enum values inside their declared sets, numbers inside their declared ranges,
    datetimes ISO 8601 UTC — on every write endpoint, otherwise `ERR_VALIDATION` (422)."

    Design: Corner/endpoints/endpoint_create_partner_org_unknown_sector_enum_rejected
    """
    pm = make_program_manager_headers()

    response = api_client.create_partner_org(
        partner_org_payload(sector="SPORTS", annual_budget_usd=MID_BUDGET), pm
    )
    validate_error(response, ApiErrorId.ERR_VALIDATION, expected_status=422)

    accepted = validate_success(
        api_client.create_partner_org(
            partner_org_payload(sector="EDUCATION", annual_budget_usd=MID_BUDGET), pm
        ),
        201,
    )
    assert accepted["sector"] == "EDUCATION", (
        f"Expected the declared sector EDUCATION to be accepted, got {accepted['sector']}"
    )
    assert accepted["capacity_class"] == "MID", (
        f"Expected capacity_class MID for a 3000000.00 budget, got {accepted['capacity_class']}"
    )


def test_10_reading_an_unknown_partner_answers_partner_org_not_found(api):
    """PRD §2.12: "The `PartnerOrg` named by a path segment exists — checked on
    `GET /partner-orgs/{id}`, `GET /partner-orgs/{id}/summary`,
    `GET /partner-orgs/{id}/satisfaction-surveys` and `PATCH /partner-orgs/{id}/status` —
    otherwise `ERR_PARTNER_ORG_NOT_FOUND` (404)."

    Design: Corner/endpoints/endpoint_get_partner_org_unknown_id_returns_not_found
    """
    pm = make_program_manager_headers()

    validate_error(
        api_client.get_partner_org(NONEXISTENT_ID, pm),
        ApiErrorId.ERR_PARTNER_ORG_NOT_FOUND,
        expected_status=404,
    )
    validate_error(
        api_client.get_partner_org_summary(NONEXISTENT_ID, pm),
        ApiErrorId.ERR_PARTNER_ORG_NOT_FOUND,
        expected_status=404,
    )


def test_11_a_fresh_partner_lists_no_satisfaction_surveys(api):
    """PRD §4 `GET /partner-orgs/{id}/satisfaction-surveys`: "Every satisfaction survey attributed
    to this partner, newest submission first, with the counted-in-index flags."
    PRD §2.3: "the `meta` block of a list response carries `limit`, `offset`, `total_count` (the
    number of rows matching the filter before pagination) and `has_more` (true when rows remain
    beyond the current page)."
    PRD §3.1: "A newly registered partner starts with `status` `ACTIVE`, a null
    `probation_reason`, a null `suspended_at`, a null `satisfaction_index`, a
    `satisfaction_sample_size` of 0 and an `open_engagement_count` of 0."

    Design: Corner/endpoints/endpoint_partner_satisfaction_surveys_empty_collection
    """
    pm = make_program_manager_headers()
    partner = create_partner(pm, annual_budget_usd=MID_BUDGET)

    rows, meta = validate_paginated(
        api_client.list_partner_org_satisfaction_surveys(partner["id"], pm)
    )

    assert rows == [], f"Expected no survey rows for a fresh partner, got {rows}"
    assert meta["total_count"] == 0, (
        f"Expected total_count 0 for a fresh partner, got {meta['total_count']}"
    )
    assert meta["has_more"] is False, (
        f"Expected has_more false on an empty collection, got {meta['has_more']}"
    )

    read_back = validate_success(api_client.get_partner_org(partner["id"], pm))
    assert read_back["satisfaction_index"] is None, (
        f"Expected a null satisfaction_index, got {read_back['satisfaction_index']}"
    )
    assert read_back["satisfaction_sample_size"] == 0, (
        f"Expected satisfaction_sample_size 0, got {read_back['satisfaction_sample_size']}"
    )


def test_12_moving_partner_standing_without_a_to_status_is_refused(api):
    """PRD §3.1: "A `ProgramManager` moves it explicitly by supplying a `to_status` and, when
    placing a partner on probation by hand, a `probation_reason` of `MANUAL` (the other reasons,
    `LOW_SATISFACTION` and `SCOPE_CREEP_ABUSE`, are set by the system)."
    PRD §2.12: "The request body conforms to the endpoint's input schema — all required fields
    present, enum values inside their declared sets, numbers inside their declared ranges,
    datetimes ISO 8601 UTC — on every write endpoint, otherwise `ERR_VALIDATION` (422)."

    Design: Corner/endpoints/endpoint_patch_partner_status_missing_to_status_rejected
    """
    pm = make_program_manager_headers()
    partner = create_partner(pm, annual_budget_usd=MID_BUDGET)

    response = api_client.patch_partner_org_status(
        partner["id"], {"probation_reason": "MANUAL"}, pm
    )
    validate_error(response, ApiErrorId.ERR_VALIDATION, expected_status=422)

    read_back = validate_success(api_client.get_partner_org(partner["id"], pm))
    assert read_back["status"] == "ACTIVE", (
        f"The refused move must leave the partner ACTIVE, got {read_back['status']}"
    )
    assert read_back["probation_reason"] is None, (
        f"Expected a null probation_reason after the refusal, got "
        f"{read_back['probation_reason']}"
    )


# ---------------------------------------------------------------------------
# Program cycle endpoints and the logical clock
# ---------------------------------------------------------------------------
def test_13_opening_a_cycle_with_no_engagement_slot_is_refused(api):
    """PRD §3.1: "A `ProgramManager` opens one with a `cycle_code` unique across cycles, an
    inclusive `starts_at`, an exclusive `ends_at` that must be strictly after it, and a
    `capacity_slot_total` of at least one engagement slot."
    PRD §2.12: "The request body conforms to the endpoint's input schema — all required fields
    present, enum values inside their declared sets, numbers inside their declared ranges,
    datetimes ISO 8601 UTC — on every write endpoint, otherwise `ERR_VALIDATION` (422)."
    PRD §3.1: "A freshly opened cycle therefore reads a `utilization_ratio` of 0.0000, a `posture`
    of `OPEN`, and a `slots_available` equal to its `capacity_slot_total`."

    Design: Corner/endpoints/endpoint_create_program_cycle_zero_capacity_rejected
    """
    pm = make_program_manager_headers()

    response = api_client.create_program_cycle(
        program_cycle_payload(capacity_slot_total=0), pm
    )
    validate_error(response, ApiErrorId.ERR_VALIDATION, expected_status=422)

    accepted = validate_success(
        api_client.create_program_cycle(program_cycle_payload(capacity_slot_total=1), pm), 201
    )
    assert accepted["capacity_slot_total"] == 1, (
        f"Expected a single-slot cycle to be accepted, got "
        f"{accepted['capacity_slot_total']}"
    )
    assert accepted["slots_available"] == 1, (
        f"Expected slots_available to equal capacity_slot_total, got "
        f"{accepted['slots_available']}"
    )
    assert float(accepted["utilization_ratio"]) == 0.0000, (
        f"Expected utilization_ratio 0.0000 on a fresh cycle, got "
        f"{accepted['utilization_ratio']}"
    )
    assert accepted["posture"] == "OPEN", (
        f"Expected posture OPEN on a fresh cycle, got {accepted['posture']}"
    )


def test_14_opening_a_cycle_whose_interval_runs_backwards_is_refused(api):
    """PRD §3.1: "A `ProgramManager` opens one with a `cycle_code` unique across cycles, an
    inclusive `starts_at`, an exclusive `ends_at` that must be strictly after it, and a
    `capacity_slot_total` of at least one engagement slot."
    PRD §2.5: "Both intervals require `ends_at` to be strictly after `starts_at`."
    PRD §2.12: "The request body conforms to the endpoint's input schema — all required fields
    present, enum values inside their declared sets, numbers inside their declared ranges,
    datetimes ISO 8601 UTC — on every write endpoint, otherwise `ERR_VALIDATION` (422)."

    Design: Corner/endpoints/endpoint_create_program_cycle_inverted_interval_rejected
    """
    pm = make_program_manager_headers()

    response = api_client.create_program_cycle(
        program_cycle_payload(starts_at="2026-12-01T00:00:00Z", ends_at="2026-08-01T00:00:00Z"),
        pm,
    )

    validate_error(response, ApiErrorId.ERR_VALIDATION, expected_status=422)


def test_15_reading_an_unknown_cycle_answers_program_cycle_not_found(api):
    """PRD §2.12: "The `ProgramCycle` named by a path segment exists — on
    `GET /program-cycles/{id}` and `POST /program-cycles/{id}/recalculate` — otherwise
    `ERR_PROGRAM_CYCLE_NOT_FOUND` (404)."
    PRD §3.1: "A freshly opened cycle therefore reads a `utilization_ratio` of 0.0000, a `posture`
    of `OPEN`, and a `slots_available` equal to its `capacity_slot_total`."

    Design: Corner/endpoints/endpoint_get_program_cycle_unknown_id_returns_not_found
    """
    pm = make_program_manager_headers()
    partner = create_partner(pm, annual_budget_usd=MID_BUDGET)
    cycle = create_cycle(pm, capacity_slot_total=4)

    validate_error(
        api_client.get_program_cycle(partner["id"], pm),
        ApiErrorId.ERR_PROGRAM_CYCLE_NOT_FOUND,
        expected_status=404,
    )

    read_back = validate_success(api_client.get_program_cycle(cycle["id"], pm))
    assert read_back["posture"] == "OPEN", (
        f"Expected the real cycle to read posture OPEN, got {read_back['posture']}"
    )
    assert read_back["slots_available"] == 4, (
        f"Expected slots_available 4 on the untouched cycle, got {read_back['slots_available']}"
    )


def test_16_recalculating_an_unknown_cycle_answers_program_cycle_not_found(api):
    """PRD §2.12: "The `ProgramCycle` named by a path segment exists — on
    `GET /program-cycles/{id}` and `POST /program-cycles/{id}/recalculate` — otherwise
    `ERR_PROGRAM_CYCLE_NOT_FOUND` (404)."
    PRD §3.1: "Finally it recomputes the capacity figures and `posture`, stamps
    `last_recalculated_at` from the clock, and advances `recalc_epoch` by exactly one — the epoch
    counter starts at 0 and exists so operators can tell one checkpoint's output from the next."

    Design: Corner/endpoints/endpoint_recalculate_unknown_cycle_returns_not_found
    """
    pm = make_program_manager_headers()
    cycle = create_cycle(pm, capacity_slot_total=4)

    validate_error(
        api_client.recalculate_program_cycle(NONEXISTENT_ID, pm),
        ApiErrorId.ERR_PROGRAM_CYCLE_NOT_FOUND,
        expected_status=404,
    )

    read_back = validate_success(api_client.get_program_cycle(cycle["id"], pm))
    assert read_back["recalc_epoch"] == 0, (
        f"The refused checkpoint must leave recalc_epoch at its 0 start, got "
        f"{read_back['recalc_epoch']}"
    )


def test_17_a_fresh_cycle_lists_no_engagements(api):
    """PRD §4 `GET /program-cycles/{id}/engagements`: "Every engagement occupying a slot in this
    cycle, including terminal ones."
    PRD §3.1: "A freshly opened cycle therefore reads a `utilization_ratio` of 0.0000, a `posture`
    of `OPEN`, and a `slots_available` equal to its `capacity_slot_total`."
    PRD §2.3: "the `meta` block of a list response carries `limit`, `offset`, `total_count` (the
    number of rows matching the filter before pagination) and `has_more` (true when rows remain
    beyond the current page)."

    Design: Corner/endpoints/endpoint_cycle_engagements_empty_collection_on_fresh_cycle
    """
    pm = make_program_manager_headers()
    cycle = create_cycle(pm, capacity_slot_total=4)

    rows, meta = validate_paginated(api_client.list_cycle_engagements(cycle["id"], pm))

    assert rows == [], f"Expected no engagement rows on a fresh cycle, got {rows}"
    assert meta["total_count"] == 0, (
        f"Expected total_count 0 on a fresh cycle, got {meta['total_count']}"
    )
    assert meta["has_more"] is False, (
        f"Expected has_more false on an empty collection, got {meta['has_more']}"
    )

    read_back = validate_success(api_client.get_program_cycle(cycle["id"], pm))
    assert read_back["slots_committed"] == 0, (
        f"Expected slots_committed 0, got {read_back['slots_committed']}"
    )
    assert read_back["slots_reserved"] == 0, (
        f"Expected slots_reserved 0, got {read_back['slots_reserved']}"
    )
    assert read_back["slots_available"] == 4, (
        f"Expected slots_available 4, got {read_back['slots_available']}"
    )
    assert float(read_back["utilization_ratio"]) == 0.0000, (
        f"Expected utilization_ratio 0.0000, got {read_back['utilization_ratio']}"
    )
    assert read_back["posture"] == "OPEN", (
        f"Expected posture OPEN, got {read_back['posture']}"
    )


def test_18_setting_the_clock_to_an_unparseable_instant_is_refused(api):
    """PRD §2.12: "The request body conforms to the endpoint's input schema — all required fields
    present, enum values inside their declared sets, numbers inside their declared ranges,
    datetimes ISO 8601 UTC — on every write endpoint, otherwise `ERR_VALIDATION` (422)."
    PRD §2.5: "The clock only moves forward: an instant strictly earlier than the current clock
    reading is rejected with `ERR_CLOCK_REGRESSION` (HTTP 422), while an instant exactly equal to
    the current reading is accepted and leaves the clock where it is."

    Design: Corner/endpoints/endpoint_clock_set_malformed_timestamp_rejected
    """
    pm = make_program_manager_headers()

    response = api_client.set_clock({"to_iso8601": "not-a-timestamp"}, pm)
    validate_error(response, ApiErrorId.ERR_VALIDATION, expected_status=422)

    validate_success(api_client.set_clock({"to_iso8601": "2026-08-01T00:00:00Z"}, pm))


# ---------------------------------------------------------------------------
# Project request endpoints
# ---------------------------------------------------------------------------
def test_19_filing_a_request_without_a_required_skill_code_is_refused(api):
    """PRD §3.3: "A `PartnerContact` files a project request against a specific program cycle,
    supplying the owning `partner_org_id`, the `cycle_id` whose capacity the work will compete
    for, a `title` of 1 to 160 characters, a `discipline` drawn from `LEGAL`, `ACCOUNTING`,
    `TECHNOLOGY`, `MARKETING`, `HR` and `STRATEGY`, the exact `required_skill_code` a candidate
    volunteer must hold, a `min_proficiency` from 1 to 5 that a candidate must meet or beat, and a
    `requested_hours` figure above zero to two decimals expressing what the partner believes the
    work needs."
    PRD §2.12: "The request body conforms to the endpoint's input schema — all required fields
    present, enum values inside their declared sets, numbers inside their declared ranges,
    datetimes ISO 8601 UTC — on every write endpoint, otherwise `ERR_VALIDATION` (422)."

    Design: Corner/endpoints/endpoint_create_project_request_missing_required_skill_code_rejected
    """
    pm = make_program_manager_headers()
    partner = create_partner(pm, annual_budget_usd=MID_BUDGET)
    cycle = create_cycle(pm, capacity_slot_total=4)
    partner_contact = make_partner_contact_headers(partner["id"])

    payload = project_request_payload(partner["id"], cycle["id"])
    payload.pop("required_skill_code")

    response = api_client.create_project_request(payload, partner_contact)
    validate_error(response, ApiErrorId.ERR_VALIDATION, expected_status=422)

    rows, meta = validate_paginated(api_client.list_project_requests(pm))
    assert meta["total_count"] == 0, (
        f"The refused filing must persist nothing, got total_count {meta['total_count']}"
    )
    assert rows == [], f"Expected no request rows after the refusal, got {rows}"


def test_20_filing_a_request_above_the_proficiency_ceiling_is_refused(api):
    """PRD §3.3: "A `PartnerContact` files a project request against a specific program cycle,
    supplying the owning `partner_org_id`, the `cycle_id` whose capacity the work will compete
    for, a `title` of 1 to 160 characters, a `discipline` drawn from `LEGAL`, `ACCOUNTING`,
    `TECHNOLOGY`, `MARKETING`, `HR` and `STRATEGY`, the exact `required_skill_code` a candidate
    volunteer must hold, a `min_proficiency` from 1 to 5 that a candidate must meet or beat, and a
    `requested_hours` figure above zero to two decimals expressing what the partner believes the
    work needs."
    PRD §2.12: "The request body conforms to the endpoint's input schema — all required fields
    present, enum values inside their declared sets, numbers inside their declared ranges,
    datetimes ISO 8601 UTC — on every write endpoint, otherwise `ERR_VALIDATION` (422)."
    PRD §3.3: "The request is created in `status` `DRAFT` with `rescope_count` 0,
    `failed_match_rounds` 0, `active_scope_revision_no` 0 and a null `closed_at`."

    Design: Corner/endpoints/endpoint_create_project_request_min_proficiency_out_of_range_rejected
    """
    pm = make_program_manager_headers()
    partner = create_partner(pm, annual_budget_usd=MID_BUDGET)
    cycle = create_cycle(pm, capacity_slot_total=4)
    partner_contact = make_partner_contact_headers(partner["id"])

    response = api_client.create_project_request(
        project_request_payload(partner["id"], cycle["id"], min_proficiency=6), partner_contact
    )
    validate_error(response, ApiErrorId.ERR_VALIDATION, expected_status=422)

    accepted = validate_success(
        api_client.create_project_request(
            project_request_payload(partner["id"], cycle["id"], min_proficiency=5),
            partner_contact,
        ),
        201,
    )
    assert accepted["min_proficiency"] == 5, (
        f"Expected the top of the declared 1-to-5 range to be accepted, got "
        f"{accepted['min_proficiency']}"
    )
    assert accepted["status"] == "DRAFT", (
        f"Expected a new request in DRAFT, got {accepted['status']}"
    )
    assert accepted["rescope_count"] == 0, (
        f"Expected rescope_count 0 on a new request, got {accepted['rescope_count']}"
    )
    assert accepted["failed_match_rounds"] == 0, (
        f"Expected failed_match_rounds 0 on a new request, got "
        f"{accepted['failed_match_rounds']}"
    )


def test_21_a_page_offset_past_the_last_request_is_an_empty_page(api):
    """PRD §2.3: "List endpoints accept two optional query parameters, `limit` and `offset`."
    PRD §2.3: "the `meta` block of a list response carries `limit`, `offset`, `total_count` (the
    number of rows matching the filter before pagination) and `has_more` (true when rows remain
    beyond the current page)."

    Design: Corner/endpoints/endpoint_project_requests_list_offset_beyond_end_returns_empty_page
    """
    pm = make_program_manager_headers()
    partner = create_partner(pm, annual_budget_usd=MID_BUDGET)
    cycle = create_cycle(pm, capacity_slot_total=4)
    partner_contact = make_partner_contact_headers(partner["id"])
    for title in ("Annual audit readiness", "Lease portfolio review"):
        validate_success(
            api_client.create_project_request(
                project_request_payload(partner["id"], cycle["id"], title=title),
                partner_contact,
            ),
            201,
        )

    rows, meta = validate_paginated(
        api_client.list_project_requests(pm, params={"offset": 5})
    )

    assert rows == [], f"Expected an empty page past the last row, got {rows}"
    assert meta["total_count"] == 2, (
        f"total_count counts the rows matching the filter before pagination, expected 2, got "
        f"{meta['total_count']}"
    )
    assert meta["offset"] == 5, (
        f"Expected the requested offset 5 echoed in meta, got {meta['offset']}"
    )
    assert meta["has_more"] is False, (
        f"Expected has_more false when no row remains beyond the page, got {meta['has_more']}"
    )

    page_rows, page_meta = validate_paginated(
        api_client.list_project_requests(pm, params={"limit": 1, "offset": 1})
    )
    assert len(page_rows) == 1, (
        f"Expected a single row at limit 1 offset 1, got {len(page_rows)}"
    )
    assert page_meta["total_count"] == 2, (
        f"Expected total_count 2 regardless of the page window, got "
        f"{page_meta['total_count']}"
    )


def test_22_a_status_filter_that_matches_no_request_returns_an_empty_page(api):
    """PRD §2.3: "Project requests may be narrowed by `partner_org_id`, `cycle_id` and `status`"
    PRD §2.3: "Filtered list endpoints combine their filter parameters conjunctively."
    PRD §3.3: "The request is created in `status` `DRAFT` with `rescope_count` 0,
    `failed_match_rounds` 0, `active_scope_revision_no` 0 and a null `closed_at`."

    Design: Corner/endpoints/endpoint_project_requests_list_status_filter_with_no_match_is_empty
    """
    world = setup_draft_request()

    rows, meta = validate_paginated(
        api_client.list_project_requests(
            world["pm_headers"],
            params={"partner_org_id": world["partner"]["id"], "status": "MATCHING"},
        )
    )
    assert rows == [], f"Expected no row for a status no request holds, got {rows}"
    assert meta["total_count"] == 0, (
        f"Expected total_count 0 for the unmatched filter, got {meta['total_count']}"
    )

    all_rows, all_meta = validate_paginated(
        api_client.list_project_requests(
            world["pm_headers"], params={"partner_org_id": world["partner"]["id"]}
        )
    )
    assert all_meta["total_count"] == 1, (
        f"Expected the one filed request without the status filter, got total_count "
        f"{all_meta['total_count']}"
    )
    assert all_rows[0]["status"] == "DRAFT", (
        f"Expected the filed request to read DRAFT, got {all_rows[0]['status']}"
    )


# ---------------------------------------------------------------------------
# Scope revision and deliverable endpoints
# ---------------------------------------------------------------------------
def test_23_drafting_a_revision_without_the_version_guard_is_refused(api):
    """PRD §2.7: "In each case the guard is a required, non-optional field in the request body
    carrying the client's last observed `version` of the named parent; a value that does not equal
    the parent's current `version` is rejected, and the write is not applied."
    PRD §2.12: "The request body conforms to the endpoint's input schema — all required fields
    present, enum values inside their declared sets, numbers inside their declared ranges,
    datetimes ISO 8601 UTC — on every write endpoint, otherwise `ERR_VALIDATION` (422)."

    Design: Corner/endpoints/endpoint_scope_definition_post_missing_expected_version_rejected
    """
    world = setup_draft_request()
    request = validate_success(
        api_client.submit_for_scoping(world["request"]["id"], world["partner_headers"])
    )

    payload = scope_definition_payload(request["version"])
    payload.pop("expected_project_request_version")

    response = api_client.create_scope_definition(
        request["id"], payload, world["spec_headers"]
    )
    validate_error(response, ApiErrorId.ERR_VALIDATION, expected_status=422)

    read_back = validate_success(
        api_client.get_project_request(request["id"], world["pm_headers"])
    )
    assert read_back["version"] == request["version"], (
        f"The refused write must not advance the request version, expected "
        f"{request['version']}, got {read_back['version']}"
    )

    rows, meta = validate_paginated(
        api_client.list_scope_definitions(
            world["pm_headers"], params={"project_request_id": request["id"]}
        )
    )
    assert meta["total_count"] == 0, (
        f"The refused write must persist no revision, got total_count {meta['total_count']}"
    )
    assert rows == [], f"Expected no revision rows after the refusal, got {rows}"


def test_24_drafting_a_revision_with_a_non_numeric_complexity_factor_is_refused(api):
    """PRD §3.3: "A `ScopingSpecialist` drafts one by supplying the mandatory
    `expected_project_request_version` described in §2.7, an `estimated_hours` figure above zero
    and no greater than 400.00, a `complexity_factor` between 1.00 and 2.50 that will multiply
    those hours when the commitment is made, the `confidentiality_tier` the deliverable falls
    under (`STANDARD`, `ELEVATED` or `RESTRICTED`), and the intended `ip_disposition` for the
    produced work (`ASSIGN_TO_PARTNER`, `LICENSE_PERPETUAL` or `RETAINED_BY_VOLUNTEER`)."
    PRD §2.12: "The request body conforms to the endpoint's input schema — all required fields
    present, enum values inside their declared sets, numbers inside their declared ranges,
    datetimes ISO 8601 UTC — on every write endpoint, otherwise `ERR_VALIDATION` (422)."

    Design: Corner/endpoints/endpoint_scope_definition_post_wrong_type_complexity_factor_rejected
    """
    world = setup_draft_request()
    request = validate_success(
        api_client.submit_for_scoping(world["request"]["id"], world["partner_headers"])
    )

    response = api_client.create_scope_definition(
        request["id"],
        scope_definition_payload(request["version"], complexity_factor="high"),
        world["spec_headers"],
    )
    validate_error(response, ApiErrorId.ERR_VALIDATION, expected_status=422)

    rows, meta = validate_paginated(
        api_client.list_scope_definitions(
            world["pm_headers"], params={"project_request_id": request["id"]}
        )
    )
    assert meta["total_count"] == 0, (
        f"The refused draft must persist no revision, got total_count {meta['total_count']}"
    )
    assert rows == [], f"Expected no revision rows after the refusal, got {rows}"


def test_25_reading_an_unknown_revision_answers_scope_definition_not_found(api):
    """PRD §2.12: "The `ScopeDefinition` named by a path segment exists — on
    `GET /scope-definitions/{id}`, `GET /scope-definitions/{id}/deliverables`,
    `POST /scope-definitions/{id}/deliverables` and `POST /scope-definitions/{id}/approve` —
    otherwise `ERR_SCOPE_DEFINITION_NOT_FOUND` (404)."
    PRD §3.3: "The new row is created in `status` `DRAFT`; its `revision_no` is one greater than
    the highest `revision_no` among its siblings on the same request, so the first is 1; its
    `authored_by_user_id` records the drafting specialist's own `X-User-ID`, which is the value the
    segregation-of-duties barrier later reads; its `deliverable_count` and
    `deliverable_weight_total_pct` both start at 0."

    Design: Corner/endpoints/endpoint_get_scope_definition_unknown_id_returns_not_found
    """
    world = setup_scoping_request()

    validate_error(
        api_client.get_scope_definition(NONEXISTENT_ID, world["reviewer_headers"]),
        ApiErrorId.ERR_SCOPE_DEFINITION_NOT_FOUND,
        expected_status=404,
    )

    read_back = validate_success(
        api_client.get_scope_definition(world["scope"]["id"], world["reviewer_headers"])
    )
    assert read_back["revision_no"] == 1, (
        f"Expected the first revision to read revision_no 1, got {read_back['revision_no']}"
    )
    assert read_back["authored_by_user_id"] == world["spec_user_id"], (
        f"Expected authored_by_user_id {world['spec_user_id']}, got "
        f"{read_back['authored_by_user_id']}"
    )


def test_26_asking_a_revision_list_for_more_than_a_hundred_rows_is_refused(api):
    """PRD §2.3: "List endpoints accept two optional query parameters, `limit` and `offset`.
    `limit` defaults to 10, must be at least 1, and may not exceed 100. `offset` defaults to 0 and
    may not be negative. Both must be integers; a `limit` below 1 or above 100, or a negative
    `offset`, is rejected with `ERR_INVALID_PAGINATION` (HTTP 400)."

    Design: Corner/endpoints/endpoint_scope_definitions_list_limit_above_ceiling_rejected
    """
    world = setup_scoping_request()

    response = api_client.list_scope_definitions(world["pm_headers"], params={"limit": 101})
    validate_error(response, ApiErrorId.ERR_INVALID_PAGINATION, expected_status=400)

    rows, meta = validate_paginated(
        api_client.list_scope_definitions(world["pm_headers"], params={"limit": 100})
    )
    assert meta["limit"] == 100, (
        f"Expected the ceiling limit 100 to be accepted and echoed, got {meta['limit']}"
    )
    assert meta["total_count"] == 1, (
        f"Expected the one drafted revision to be listed, got total_count "
        f"{meta['total_count']}"
    )
    assert rows[0]["id"] == world["scope"]["id"], (
        f"Expected the listed revision to be {world['scope']['id']}, got {rows[0]['id']}"
    )


def test_27_adding_a_deliverable_without_acceptance_criteria_is_refused(api):
    """PRD §3.3: "The same `ScopingSpecialist` adds deliverables to a `DRAFT` revision one at a
    time, each carrying a `title` of 1 to 120 characters, a `sequence_no` of at least 1 that must
    be unique within the revision and that becomes the primary sort key for quality scoring, a
    `weight_pct` between 0.01 and 100.00 expressing the item's share of the whole, an
    `hours_estimate` above zero, and an `acceptance_criteria` prose bar of 1 to 500 characters
    that the quality reviewer will judge against."
    PRD §2.12: "The request body conforms to the endpoint's input schema — all required fields
    present, enum values inside their declared sets, numbers inside their declared ranges,
    datetimes ISO 8601 UTC — on every write endpoint, otherwise `ERR_VALIDATION` (422)."

    Design: Corner/endpoints/endpoint_deliverable_post_missing_acceptance_criteria_rejected
    """
    world = setup_scoping_request(deliverables=[])

    payload = deliverable_payload()
    payload.pop("acceptance_criteria")

    response = api_client.create_deliverable(
        world["scope"]["id"], payload, world["spec_headers"]
    )
    validate_error(response, ApiErrorId.ERR_VALIDATION, expected_status=422)

    rows, meta = validate_paginated(
        api_client.list_deliverables(world["scope"]["id"], world["spec_headers"])
    )
    assert meta["total_count"] == 0, (
        f"The refused deliverable must persist nothing, got total_count {meta['total_count']}"
    )
    assert rows == [], f"Expected no deliverable rows after the refusal, got {rows}"

    read_back = validate_success(
        api_client.get_scope_definition(world["scope"]["id"], world["spec_headers"])
    )
    assert read_back["deliverable_count"] == 0, (
        f"Expected deliverable_count 0 after the refusal, got {read_back['deliverable_count']}"
    )
    assert float(read_back["deliverable_weight_total_pct"]) == 0.00, (
        f"Expected deliverable_weight_total_pct 0.00 after the refusal, got "
        f"{read_back['deliverable_weight_total_pct']}"
    )


def test_28_adding_a_deliverable_with_a_non_numeric_sequence_no_is_refused(api):
    """PRD §3.3: "The same `ScopingSpecialist` adds deliverables to a `DRAFT` revision one at a
    time, each carrying a `title` of 1 to 120 characters, a `sequence_no` of at least 1 that must
    be unique within the revision and that becomes the primary sort key for quality scoring, a
    `weight_pct` between 0.01 and 100.00 expressing the item's share of the whole, an
    `hours_estimate` above zero, and an `acceptance_criteria` prose bar of 1 to 500 characters
    that the quality reviewer will judge against."
    PRD §2.12: "The request body conforms to the endpoint's input schema — all required fields
    present, enum values inside their declared sets, numbers inside their declared ranges,
    datetimes ISO 8601 UTC — on every write endpoint, otherwise `ERR_VALIDATION` (422)."

    Design: Corner/endpoints/endpoint_deliverable_post_wrong_type_sequence_no_rejected
    """
    world = setup_scoping_request(
        deliverables=[
            {
                "title": "Findings memo",
                "sequence_no": 1,
                "weight_pct": 60.00,
                "hours_estimate": 24.00,
                "acceptance_criteria": "Board-ready memo with cited findings.",
            }
        ]
    )

    response = api_client.create_deliverable(
        world["scope"]["id"],
        deliverable_payload(title="Remediation plan", sequence_no="first", weight_pct=40.00),
        world["spec_headers"],
    )
    validate_error(response, ApiErrorId.ERR_VALIDATION, expected_status=422)

    rows, meta = validate_paginated(
        api_client.list_deliverables(world["scope"]["id"], world["spec_headers"])
    )
    assert meta["total_count"] == 1, (
        f"Only the first deliverable may survive, got total_count {meta['total_count']}"
    )
    assert rows[0]["sequence_no"] == 1, (
        f"Expected the surviving deliverable to read sequence_no 1, got "
        f"{rows[0]['sequence_no']}"
    )

    read_back = validate_success(
        api_client.get_scope_definition(world["scope"]["id"], world["spec_headers"])
    )
    assert read_back["deliverable_count"] == 1, (
        f"Expected deliverable_count 1 after the refusal, got {read_back['deliverable_count']}"
    )
    assert float(read_back["deliverable_weight_total_pct"]) == 60.00, (
        f"Expected deliverable_weight_total_pct 60.00 after the refusal, got "
        f"{read_back['deliverable_weight_total_pct']}"
    )


def test_29_a_fresh_revision_lists_no_deliverables(api):
    """PRD §4 `GET /scope-definitions/{id}/deliverables`: "Deliverables of one scope revision in
    sequence order, with review state and score."
    PRD §3.3: "The new row is created in `status` `DRAFT`; its `revision_no` is one greater than
    the highest `revision_no` among its siblings on the same request, so the first is 1; its
    `authored_by_user_id` records the drafting specialist's own `X-User-ID`, which is the value the
    segregation-of-duties barrier later reads; its `deliverable_count` and
    `deliverable_weight_total_pct` both start at 0."

    Design: Corner/endpoints/endpoint_deliverables_empty_collection_on_fresh_revision
    """
    world = setup_scoping_request(deliverables=[])

    rows, meta = validate_paginated(
        api_client.list_deliverables(world["scope"]["id"], world["volunteer_headers"])
    )
    assert rows == [], f"Expected no deliverable rows on a fresh revision, got {rows}"
    assert meta["total_count"] == 0, (
        f"Expected total_count 0 on a fresh revision, got {meta['total_count']}"
    )
    assert meta["has_more"] is False, (
        f"Expected has_more false on an empty collection, got {meta['has_more']}"
    )

    read_back = validate_success(
        api_client.get_scope_definition(world["scope"]["id"], world["volunteer_headers"])
    )
    assert read_back["status"] == "DRAFT", (
        f"Expected the revision to read DRAFT, got {read_back['status']}"
    )
    assert read_back["revision_no"] == 1, (
        f"Expected revision_no 1 on the first revision, got {read_back['revision_no']}"
    )
    assert read_back["deliverable_count"] == 0, (
        f"Expected deliverable_count 0, got {read_back['deliverable_count']}"
    )
    assert float(read_back["deliverable_weight_total_pct"]) == 0.00, (
        f"Expected deliverable_weight_total_pct 0.00, got "
        f"{read_back['deliverable_weight_total_pct']}"
    )


# ---------------------------------------------------------------------------
# Volunteer endpoints
# ---------------------------------------------------------------------------
def test_30_enrolling_a_volunteer_with_a_negative_hours_cap_is_refused(api):
    """PRD §3.2: "Volunteers are enrolled by a `ProgramManager` with a `full_name` of 1 to 120
    characters, a unique `email`, a self-declared `professional_rate_usd_per_hour` that must be
    above zero and no greater than 2000.00, a `seniority` of `ASSOCIATE`, `SENIOR`, `PRINCIPAL` or
    `PARTNER`, and a `weekly_hours_cap` between 1 and 40 hours."
    PRD §2.12: "The request body conforms to the endpoint's input schema — all required fields
    present, enum values inside their declared sets, numbers inside their declared ranges,
    datetimes ISO 8601 UTC — on every write endpoint, otherwise `ERR_VALIDATION` (422)."
    PRD §3.2: "Enrolment lands the volunteer in `status` `PENDING_VETTING` with
    `credential_verified_at` null, both `reliability_score` and `reliability_score_lifetime`
    seeded at the 0.7500 baseline, `lifetime_valued_usd` at 0.00, and `terminal_engagement_count`
    and `open_engagement_count` at 0."

    Design: Corner/endpoints/endpoint_create_volunteer_negative_weekly_hours_cap_rejected
    """
    pm = make_program_manager_headers()

    response = api_client.create_volunteer(volunteer_payload(weekly_hours_cap=-5), pm)
    validate_error(response, ApiErrorId.ERR_VALIDATION, expected_status=422)

    accepted = validate_success(
        api_client.create_volunteer(volunteer_payload(weekly_hours_cap=20), pm), 201
    )
    assert accepted["weekly_hours_cap"] == 20, (
        f"Expected a cap inside the declared 1-to-40 range to be accepted, got "
        f"{accepted['weekly_hours_cap']}"
    )
    assert accepted["status"] == "PENDING_VETTING", (
        f"Expected a new volunteer in PENDING_VETTING, got {accepted['status']}"
    )
    assert accepted["credential_verified_at"] is None, (
        f"Expected a null credential_verified_at before vetting, got "
        f"{accepted['credential_verified_at']}"
    )
    assert float(accepted["reliability_score"]) == 0.7500, (
        f"Expected the 0.7500 reliability baseline, got {accepted['reliability_score']}"
    )
    assert float(accepted["lifetime_valued_usd"]) == 0.00, (
        f"Expected lifetime_valued_usd 0.00, got {accepted['lifetime_valued_usd']}"
    )


def test_31_reading_an_unknown_volunteer_answers_volunteer_not_found(api):
    """PRD §2.12: "The `Volunteer` named by a path segment exists — on `GET /volunteers/{id}`,
    `GET /volunteers/{id}/skill-profiles`, `GET /volunteers/{id}/availability-windows`,
    `POST /volunteers/{id}/vet`, `PATCH /volunteers/{id}/status`,
    `POST /volunteers/{id}/skill-profiles` and `POST /volunteers/{id}/availability-windows` —
    otherwise `ERR_VOLUNTEER_NOT_FOUND` (404)."

    Design: Corner/endpoints/endpoint_get_volunteer_unknown_id_returns_not_found
    """
    pm = make_program_manager_headers()
    volunteer = create_volunteer(pm)

    validate_error(
        api_client.get_volunteer(NONEXISTENT_ID, pm),
        ApiErrorId.ERR_VOLUNTEER_NOT_FOUND,
        expected_status=404,
    )
    validate_error(
        api_client.list_skill_profiles(NONEXISTENT_ID, pm),
        ApiErrorId.ERR_VOLUNTEER_NOT_FOUND,
        expected_status=404,
    )

    read_back = validate_success(api_client.get_volunteer(volunteer["id"], pm))
    assert read_back["id"] == volunteer["id"], (
        f"The enrolled volunteer must still resolve, expected {volunteer['id']}, got "
        f"{read_back['id']}"
    )


def test_32_vetting_that_names_an_unheld_skill_code_verifies_no_claim(api):
    """PRD §3.2: "Vetting is a single `ProgramManager` action that stamps
    `credential_verified_at` from the logical clock, flips `status` from `PENDING_VETTING` to
    `ACTIVE`, and optionally accepts a `verify_skill_codes` list; each skill claim whose
    `skill_code` appears on that list has its `verified` flag set to true and its `verified_at`
    stamped, which is what later earns that claim a bonus in the matching score."
    PRD §3.2: "The pair of the owning `volunteer_id` and the `skill_code` must be unique — a second
    claim on the same code is refused with `ERR_DUPLICATE_SKILL_PROFILE` — and `verified` defaults
    to false until a vetting run names that code."

    Design: Corner/endpoints/endpoint_vet_with_unrecognised_skill_code_verifies_nothing
    """
    pm = make_program_manager_headers()
    volunteer = create_volunteer(pm)
    claim = create_skill_profile(volunteer["id"], skill_code="TAX_LAW", proficiency=4)

    vetted = validate_success(
        api_client.vet_volunteer(
            volunteer["id"], {"verify_skill_codes": ["PATENT_LAW"]}, pm
        )
    )

    assert vetted["status"] == "ACTIVE", (
        f"Vetting must still activate the volunteer, got {vetted['status']}"
    )
    assert _instant(vetted["credential_verified_at"]) == _instant("2026-08-01T00:00:00Z"), (
        f"Expected credential_verified_at stamped from the logical clock, got "
        f"{vetted['credential_verified_at']}"
    )

    rows, meta = validate_paginated(api_client.list_skill_profiles(volunteer["id"], pm))
    assert meta["total_count"] == 1, (
        f"Expected the one declared claim, got total_count {meta['total_count']}"
    )
    assert rows[0]["id"] == claim["id"], (
        f"Expected the declared claim {claim['id']}, got {rows[0]['id']}"
    )
    assert rows[0]["verified"] is False, (
        f"A claim whose code the vetting run never named must stay unverified, got "
        f"{rows[0]['verified']}"
    )
    assert rows[0]["verified_at"] is None, (
        f"Expected a null verified_at on the unverified claim, got {rows[0]['verified_at']}"
    )


def test_33_a_volunteer_with_no_claims_lists_no_skill_profiles(api):
    """PRD §4 `GET /volunteers/{id}/skill-profiles`: "Skill claims of one volunteer with
    proficiency and verification flags."
    PRD §3.2: "Enrolment lands the volunteer in `status` `PENDING_VETTING` with
    `credential_verified_at` null, both `reliability_score` and `reliability_score_lifetime`
    seeded at the 0.7500 baseline, `lifetime_valued_usd` at 0.00, and `terminal_engagement_count`
    and `open_engagement_count` at 0."

    Design: Corner/endpoints/endpoint_volunteer_skill_profiles_empty_collection
    """
    pm = make_program_manager_headers()
    volunteer = create_volunteer(pm)

    rows, meta = validate_paginated(
        api_client.list_skill_profiles(volunteer["id"], make_volunteer_headers(volunteer["id"]))
    )

    assert rows == [], f"Expected no claim rows before any declaration, got {rows}"
    assert meta["total_count"] == 0, (
        f"Expected total_count 0 before any declaration, got {meta['total_count']}"
    )
    assert meta["has_more"] is False, (
        f"Expected has_more false on an empty collection, got {meta['has_more']}"
    )

    read_back = validate_success(api_client.get_volunteer(volunteer["id"], pm))
    assert read_back["status"] == "PENDING_VETTING", (
        f"Expected the volunteer to sit in PENDING_VETTING, got {read_back['status']}"
    )
    assert read_back["credential_verified_at"] is None, (
        f"Expected a null credential_verified_at before vetting, got "
        f"{read_back['credential_verified_at']}"
    )


def test_34_a_vetted_volunteer_with_no_window_lists_no_availability(api):
    """PRD §4 `GET /volunteers/{id}/availability-windows`: "Availability windows of one volunteer
    with committed and remaining hours."
    PRD §3.2: "Vetting is a single `ProgramManager` action that stamps `credential_verified_at`
    from the logical clock, flips `status` from `PENDING_VETTING` to `ACTIVE`, and optionally
    accepts a `verify_skill_codes` list; each skill claim whose `skill_code` appears on that list
    has its `verified` flag set to true and its `verified_at` stamped, which is what later earns
    that claim a bonus in the matching score."

    Design: Corner/endpoints/endpoint_volunteer_availability_windows_empty_collection
    """
    pm = make_program_manager_headers()
    volunteer, _claim, _window = create_vetted_volunteer(window=False)

    rows, meta = validate_paginated(
        api_client.list_availability_windows(volunteer["id"], pm)
    )

    assert rows == [], f"Expected no window rows before any is published, got {rows}"
    assert meta["total_count"] == 0, (
        f"Expected total_count 0 before any window is published, got {meta['total_count']}"
    )
    assert meta["has_more"] is False, (
        f"Expected has_more false on an empty collection, got {meta['has_more']}"
    )

    read_back = validate_success(api_client.get_volunteer(volunteer["id"], pm))
    assert read_back["status"] == "ACTIVE", (
        f"Expected the vetted volunteer to read ACTIVE, got {read_back['status']}"
    )
    assert read_back["open_engagement_count"] == 0, (
        f"Expected open_engagement_count 0, got {read_back['open_engagement_count']}"
    )


# ---------------------------------------------------------------------------
# Match offer and engagement endpoints
# ---------------------------------------------------------------------------
def test_35_offer_filters_return_an_empty_page_before_any_match_runs(api):
    """PRD §2.3: "Project requests may be narrowed by `partner_org_id`, `cycle_id` and `status`;
    scope revisions by `project_request_id`, `supersedes_scope_id` and `status` — supplying
    `supersedes_scope_id` walks the revision chain forward from any revision; match offers by
    `project_request_id`, `volunteer_id`, `scope_definition_id`, `availability_window_id` and
    `status`; engagements by `match_offer_id`, `project_request_id`, `volunteer_id`,
    `scope_definition_id`, `cycle_id`, `availability_window_id` and `work_status`."
    PRD §2.3: "Filtered list endpoints combine their filter parameters conjunctively."

    Design: Corner/endpoints/endpoint_match_offers_list_filter_empty_before_any_match
    """
    world = setup_scoped_request()

    rows, meta = validate_paginated(
        api_client.list_match_offers(
            world["pm_headers"],
            params={"volunteer_id": world["volunteer"]["id"], "status": "OFFERED"},
        )
    )

    assert rows == [], f"Expected no offer rows before the selector runs, got {rows}"
    assert meta["total_count"] == 0, (
        f"Expected total_count 0 before the selector runs, got {meta['total_count']}"
    )

    request_rows, request_meta = validate_paginated(
        api_client.list_match_offers(
            world["pm_headers"], params={"project_request_id": world["request"]["id"]}
        )
    )
    assert request_rows == [], (
        f"Expected no offer rows under the request filter, got {request_rows}"
    )
    assert request_meta["total_count"] == 0, (
        f"Expected total_count 0 under the request filter, got {request_meta['total_count']}"
    )


def test_36_reading_an_unknown_offer_answers_match_offer_not_found(api):
    """PRD §2.12: "The `MatchOffer` named by a path segment exists — on `GET /match-offers/{id}`,
    `POST /match-offers/{id}/accept`, `POST /match-offers/{id}/decline` and
    `POST /match-offers/{id}/withdraw` — otherwise `ERR_MATCH_OFFER_NOT_FOUND` (404)."

    Design: Corner/endpoints/endpoint_get_match_offer_unknown_id_returns_not_found
    """
    world = setup_scoped_request()

    validate_error(
        api_client.get_match_offer(NONEXISTENT_ID, world["pm_headers"]),
        ApiErrorId.ERR_MATCH_OFFER_NOT_FOUND,
        expected_status=404,
    )

    rows, meta = validate_paginated(
        api_client.list_match_offers(world["pm_headers"], params={"status": "OFFERED"})
    )
    assert rows == [], f"Expected no offer rows to exist at all, got {rows}"
    assert meta["total_count"] == 0, (
        f"Expected total_count 0 with no offer written, got {meta['total_count']}"
    )


def test_37_asking_the_engagement_list_for_a_negative_offset_is_refused(api):
    """PRD §2.3: "List endpoints accept two optional query parameters, `limit` and `offset`.
    `limit` defaults to 10, must be at least 1, and may not exceed 100. `offset` defaults to 0 and
    may not be negative. Both must be integers; a `limit` below 1 or above 100, or a negative
    `offset`, is rejected with `ERR_INVALID_PAGINATION` (HTTP 400)."

    Design: Corner/endpoints/endpoint_engagements_list_negative_offset_rejected
    """
    pm = make_program_manager_headers()

    response = api_client.list_engagements(pm, params={"offset": -1})
    validate_error(response, ApiErrorId.ERR_INVALID_PAGINATION, expected_status=400)

    rows, meta = validate_paginated(api_client.list_engagements(pm, params={"offset": 0}))
    assert rows == [], f"Expected no engagement rows in an empty program, got {rows}"
    assert meta["offset"] == 0, (
        f"Expected the accepted offset 0 echoed in meta, got {meta['offset']}"
    )
    assert meta["total_count"] == 0, (
        f"Expected total_count 0 in an empty program, got {meta['total_count']}"
    )


def test_38_a_work_status_filter_no_engagement_holds_returns_an_empty_page(api):
    """PRD §2.3: "Project requests may be narrowed by `partner_org_id`, `cycle_id` and `status`;
    scope revisions by `project_request_id`, `supersedes_scope_id` and `status` — supplying
    `supersedes_scope_id` walks the revision chain forward from any revision; match offers by
    `project_request_id`, `volunteer_id`, `scope_definition_id`, `availability_window_id` and
    `status`; engagements by `match_offer_id`, `project_request_id`, `volunteer_id`,
    `scope_definition_id`, `cycle_id`, `availability_window_id` and `work_status`."
    PRD §3.5: "**Step one:** the new engagement is written with `work_status` `NOT_STARTED` and
    `valuation_status` `UNVALUED`, its `match_offer_id` pointing at the accepted offer, its
    `project_request_id`, `volunteer_id`, `cycle_id` and `availability_window_id` copied from the
    offer and its request, its `scope_definition_id` pinned to the offer's revision and never
    re-pointed afterwards, and its `committed_hours` seeded from the offer's `reserved_hours`."

    Design: Corner/endpoints/endpoint_engagements_list_work_status_filter_empty
    """
    world = setup_engagement()

    for absent_status in ("HANDED_OFF", "IN_PROGRESS"):
        rows, meta = validate_paginated(
            api_client.list_engagements(
                world["pm_headers"], params={"work_status": absent_status}
            )
        )
        assert rows == [], (
            f"Expected no row for work_status {absent_status}, got {rows}"
        )
        assert meta["total_count"] == 0, (
            f"Expected total_count 0 for work_status {absent_status}, got "
            f"{meta['total_count']}"
        )

    live_rows, live_meta = validate_paginated(
        api_client.list_engagements(world["pm_headers"], params={"work_status": "NOT_STARTED"})
    )
    assert live_meta["total_count"] == 1, (
        f"Expected the accepted engagement under NOT_STARTED, got total_count "
        f"{live_meta['total_count']}"
    )
    assert live_rows[0]["id"] == world["engagement"]["id"], (
        f"Expected {world['engagement']['id']} under the NOT_STARTED filter, got "
        f"{live_rows[0]['id']}"
    )


def test_39_reading_an_unknown_milestone_answers_milestone_not_found(api):
    """PRD §2.12: "The `Milestone` named by a path segment exists — on `GET /milestones/{id}`,
    `GET /milestones/{id}/time-logs` and `POST /milestones/{id}/hold` — otherwise
    `ERR_MILESTONE_NOT_FOUND` (404)."

    Design: Corner/endpoints/endpoint_get_milestone_unknown_id_returns_not_found
    """
    pm = make_program_manager_headers()

    validate_error(
        api_client.get_milestone(NONEXISTENT_ID, pm),
        ApiErrorId.ERR_MILESTONE_NOT_FOUND,
        expected_status=404,
    )
    validate_error(
        api_client.list_milestone_time_logs(NONEXISTENT_ID, pm),
        ApiErrorId.ERR_MILESTONE_NOT_FOUND,
        expected_status=404,
    )


def test_40_an_engagement_lists_no_agreement_and_cannot_start_before_one_is_issued(api):
    """PRD §4 `GET /engagements/{id}/agreements`: "Agreement rows of one engagement, newest first,
    including voided predecessors."
    PRD §3.6: "An engagement whose agreement has not reached `EXECUTED` cannot be started and
    cannot receive time logs; both are refused with `ERR_AGREEMENT_NOT_EXECUTED`."
    PRD §3.5: "**Step one:** the new engagement is written with `work_status` `NOT_STARTED` and
    `valuation_status` `UNVALUED`, its `match_offer_id` pointing at the accepted offer, its
    `project_request_id`, `volunteer_id`, `cycle_id` and `availability_window_id` copied from the
    offer and its request, its `scope_definition_id` pinned to the offer's revision and never
    re-pointed afterwards, and its `committed_hours` seeded from the offer's `reserved_hours`."

    Design: Corner/endpoints/endpoint_engagement_agreements_empty_before_first_issue
    """
    world = setup_engagement()
    engagement_id = world["engagement"]["id"]

    rows, meta = validate_paginated(
        api_client.list_agreements(engagement_id, world["pm_headers"])
    )
    assert rows == [], f"Expected no agreement rows before the first issue, got {rows}"
    assert meta["total_count"] == 0, (
        f"Expected total_count 0 before the first issue, got {meta['total_count']}"
    )

    response = api_client.start_engagement(engagement_id, world["volunteer_headers"])
    validate_error(response, ApiErrorId.ERR_AGREEMENT_NOT_EXECUTED, expected_status=409)

    engagement = read_engagement(world)
    assert engagement["work_status"] == "NOT_STARTED", (
        f"The refused start must leave the engagement NOT_STARTED, got "
        f"{engagement['work_status']}"
    )
    assert float(engagement["committed_hours"]) == 40.00, (
        f"Expected committed_hours 40.00 seeded from the offer's reserved hours, got "
        f"{engagement['committed_hours']}"
    )

    milestone_rows, milestone_meta = validate_paginated(
        api_client.list_milestones(engagement_id, world["pm_headers"])
    )
    assert milestone_meta["total_count"] == 0, (
        f"Expected no milestones on an unstarted engagement, got total_count "
        f"{milestone_meta['total_count']}"
    )
    assert milestone_rows == [], f"Expected an empty milestone list, got {milestone_rows}"

    log_rows, log_meta = validate_paginated(
        api_client.list_time_logs(engagement_id, world["pm_headers"])
    )
    assert log_meta["total_count"] == 0, (
        f"Expected no time logs on an unstarted engagement, got total_count "
        f"{log_meta['total_count']}"
    )
    assert log_rows == [], f"Expected an empty time-log list, got {log_rows}"
