"""Registry-record behaviour: creation echoes, declared defaults, computed
starting values, system fields, existence errors, schema refusals, foreign-key
resolution, listings and flat-topology filtering (PRD §2.3, §2.4, §2.5, §3.1,
§3.2, §3.3, §3.7).
"""

from test_helpers import (
    NON_EXISTENT_UUID,
    assert_common_fields,
    assert_field,
    assert_fields,
    assert_ledger,
    assert_two_decimals,
    assert_version,
    ids_of,
    incident_payload,
    is_iso8601_timestamp,
    link_signal,
    make_comms_lead_headers,
    make_incident_lead_headers,
    make_program_admin_headers,
    make_social_listener_headers,
    media_interview_payload,
    monitored_channel_payload,
    open_incident,
    prepared_material_payload,
    read_signal,
    record_signal,
    register_member,
    setup_monitoring_incident,
    team_member_payload,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_team_member_creation_echoes_inputs_and_zeroes_both_ledgers(api):
    """PRD §3.1: "Registering a person on the crisis roster requires a `full_name`
    and an `org_title`, each non-empty and no longer than 120 characters ...
    `privilege_cleared` is a boolean that defaults to false ...
    `media_training_status` defaults to `NONE` and may be set to `CURRENT`; when
    it is `CURRENT`, `media_training_expires_at` records the instant at which that
    currency lapses ... A newly registered member begins with
    `scheduled_interview_minutes` of 0 and `active_assignment_count` of 0."

    Design: Corner/entities/corner_team_member_creation_returns_declared_fields
    """
    response = api.create_team_member(
        team_member_payload(
            full_name="Mara Vance",
            org_title="Chief Spokesperson",
            privilege_cleared=True,
            media_training_status="CURRENT",
            media_training_expires_at="2026-12-01T00:00:00.000Z",
        ),
        make_program_admin_headers(),
    )
    member = validate_success(response, 201)

    assert_fields(
        member,
        {
            "full_name": "Mara Vance",
            "org_title": "Chief Spokesperson",
            "privilege_cleared": True,
            "media_training_status": "CURRENT",
        },
        "TeamMember",
    )
    assert is_iso8601_timestamp(member.get("media_training_expires_at")), (
        "media_training_expires_at must be an ISO 8601 UTC instant, got "
        f"{member.get('media_training_expires_at')!r}"
    )
    assert member["media_training_expires_at"].startswith("2026-12-01T00:00:00"), (
        "media_training_expires_at must record the supplied lapse instant, got "
        f"{member['media_training_expires_at']!r}"
    )
    assert_ledger(member, "scheduled_interview_minutes", 0)
    assert_ledger(member, "active_assignment_count", 0)

    assert_common_fields(member, "TeamMember")
    assert_version(member, 1, "TeamMember")
    assert_field(member, "updated_at", member["created_at"], "TeamMember")


def test_monitored_channel_defaults_applied_when_optional_input_omitted(api):
    """PRD §3.1: "A `platform_escalation_contact` may optionally be recorded,
    defaulting to null ... `max_concurrent_corrections` expresses how many
    overlapping correction windows the channel tolerates at once; it defaults to 1
    and must be at least 1 and no more than 5. Every new channel starts with
    `escalation_path_state` of `UNVERIFIED`, a null `verified_contact_reference`,
    `reserved_correction_minutes` of 0 and `open_escalation_count` of 0."

    Design: Corner/entities/corner_monitored_channel_defaults_applied_when_optional_input_omitted
    """
    response = api.create_monitored_channel(
        monitored_channel_payload(name="Platform X", channel_type="SOCIAL"),
        make_program_admin_headers(),
    )
    channel = validate_success(response, 201)

    assert_fields(
        channel,
        {
            "name": "Platform X",
            "channel_type": "SOCIAL",
            "escalation_path_state": "UNVERIFIED",
            "verified_contact_reference": None,
            "platform_escalation_contact": None,
            "max_concurrent_corrections": 1,
        },
        "MonitoredChannel",
    )
    assert_ledger(channel, "reserved_correction_minutes", 0)
    assert_ledger(channel, "open_escalation_count", 0)
    assert_common_fields(channel, "MonitoredChannel")
    assert_version(channel, 1, "MonitoredChannel")


def test_prepared_material_computed_readiness_starts_at_draft_zero(api):
    """PRD §3.1: "Freshly filed material sits in `readiness_state` `DRAFT` with a
    `readiness_score` of 0.00, a null `last_reviewed_at` and null
    `reviewer_notes`; it is not yet counted as ready for anything."

    Design: Corner/entities/corner_prepared_material_computed_fields_start_at_draft_zero
    """
    comms = register_member(full_name="Ivo Berg", org_title="Comms Director")

    response = api.create_prepared_material(
        prepared_material_payload(
            scenario_code="DATA_BREACH",
            material_type="DARK_SITE_PAGE",
            title="Breach dark site",
        ),
        make_comms_lead_headers(comms["id"]),
    )
    material = validate_success(response, 201)

    assert_fields(
        material,
        {
            "scenario_code": "DATA_BREACH",
            "material_type": "DARK_SITE_PAGE",
            "title": "Breach dark site",
            "readiness_state": "DRAFT",
            "last_reviewed_at": None,
            "reviewer_notes": None,
            "dark_site_url": None,
        },
        "PreparedMaterial",
    )
    assert_two_decimals(material.get("readiness_score"), 0.00, "readiness_score")
    assert_common_fields(material, "PreparedMaterial")
    assert_version(material, 1, "PreparedMaterial")


def test_incident_system_fields_are_server_minted_and_client_copies_rejected(api):
    """PRD §2.5: "An unknown field in any request body, or an enum filter value
    outside the declared set, is rejected with `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/entities/corner_incident_system_fields_generated_and_extra_field_rejected
    """
    lead = register_member(full_name="Dana Ruiz", org_title="VP Operations")
    lead_headers = make_incident_lead_headers(lead["id"])
    supplied_id = "00000000-0000-0000-0000-00000000aaaa"

    rejected = api.create_incident(
        incident_payload(
            title="Rumour of a plant closure",
            scenario_code="PLANT_INCIDENT",
            id=supplied_id,
            version=9,
        ),
        lead_headers,
    )
    validate_error(rejected, "ERR_INVALID_REQUEST")

    accepted = api.create_incident(
        incident_payload(
            title="Rumour of a plant closure", scenario_code="PLANT_INCIDENT"
        ),
        lead_headers,
    )
    incident = validate_success(accepted, 201)

    assert incident["id"] != supplied_id, (
        "id must be server-minted, not the client-supplied value"
    )
    assert_common_fields(incident, "Incident")
    assert_version(incident, 1, "Incident")
    assert_field(incident, "updated_at", incident["created_at"], "Incident")
    assert_field(incident, "created_by_member_id", lead["id"], "Incident")


def test_issue_signal_unknown_path_id_returns_signal_specific_not_found(api):
    """PRD §2.5: "Path identifiers are resolved left to right before any body field
    is inspected, and an identifier that does not resolve produces the
    resource-specific not-found error at HTTP 404 — `ERR_TEAM_MEMBER_NOT_FOUND`,
    `ERR_CHANNEL_NOT_FOUND`, `ERR_INCIDENT_NOT_FOUND`, `ERR_SIGNAL_NOT_FOUND`..."

    Design: Corner/entities/corner_issue_signal_unknown_id_returns_not_found
    """
    listener = register_member(full_name="Ray Lund", org_title="Social Analyst")

    response = api.get_issue_signal(
        NON_EXISTENT_UUID, make_social_listener_headers(listener["id"])
    )
    error = validate_error(response, "ERR_SIGNAL_NOT_FOUND")
    assert error["message"].strip(), "the error message must be a non-empty string"


def test_prepared_material_missing_material_type_rejected_and_nothing_stored(api):
    """PRD §3.1: "A prepared material is filed against a `scenario_code`, one of
    `PRODUCT_RECALL`, `DATA_BREACH`, `EXEC_MISCONDUCT`, `PLANT_INCIDENT` or
    `REGULATORY_PROBE`, and a `material_type`, one of `DARK_SITE_PAGE`, `FAQ`,
    `HOLDING_TEMPLATE` or `EXEC_BRIEF`."

    Design: Corner/entities/corner_prepared_material_missing_required_field_rejected
    """
    comms = register_member(full_name="Ivo Berg", org_title="Comms Director")
    comms_headers = make_comms_lead_headers(comms["id"])

    payload = prepared_material_payload(
        scenario_code="DATA_BREACH", title="Breach FAQ"
    )
    del payload["material_type"]

    response = api.create_prepared_material(payload, comms_headers)
    validate_error(response, "ERR_INVALID_REQUEST")

    rows, meta = validate_paginated(api.list_prepared_materials(comms_headers))
    assert meta["total_count"] == 0, (
        f"no material may be stored by a rejected create, found {meta['total_count']}"
    )
    assert rows == [], f"expected an empty prepared-material collection, got {rows}"


def test_monitored_channel_channel_type_outside_the_enum_rejected(api):
    """PRD §3.1: "A monitored channel needs a `name` — non-empty, at most 120
    characters — and a `channel_type` that is one of `MEDIA`, `SOCIAL` or
    `REGULATORY`, naming whether the surface is an outlet, a social platform or a
    regulator docket."

    Design: Corner/entities/corner_monitored_channel_invalid_enum_value_rejected
    """
    admin_headers = make_program_admin_headers()

    response = api.create_monitored_channel(
        monitored_channel_payload(name="Podcast network", channel_type="PODCAST"),
        admin_headers,
    )
    validate_error(response, "ERR_INVALID_REQUEST")

    rows, meta = validate_paginated(api.list_monitored_channels(admin_headers))
    assert meta["total_count"] == 0, (
        f"no channel may be stored by a rejected create, found {meta['total_count']}"
    )
    assert rows == [], f"expected an empty channel collection, got {rows}"


def test_media_interview_unresolvable_spokesperson_fk_returns_member_not_found(api):
    """PRD §2.5: "The same catalogue governs foreign keys carried in a request
    body: an `incident_id`, `channel_id`, `member_id`, `statement_id`,
    `spokesperson_member_id`, `supersedes_statement_id` or
    `correction_statement_id` that does not resolve produces the not-found error
    belonging to the referenced resource type, also at HTTP 404."

    Design: Corner/entities/corner_media_interview_unknown_spokesperson_fk_returns_not_found
    """
    scenario = setup_monitoring_incident(
        clock="2026-08-10T09:00:00Z",
        scenario_code="PLANT_INCIDENT",
        title="Inspection follow-up",
    )
    incident_id = scenario["incident"]["id"]
    comms_headers = scenario["headers"]["comms"]

    response = api.create_media_interview(
        media_interview_payload(
            incident_id,
            NON_EXISTENT_UUID,
            scenario["channel"]["id"],
            "2026-08-12T14:00:00Z",
            "2026-08-12T15:00:00Z",
            outlet_name="Wire Morning",
        ),
        comms_headers,
    )
    validate_error(response, "ERR_TEAM_MEMBER_NOT_FOUND")

    rows, meta = validate_paginated(
        api.list_media_interviews(comms_headers, {"incident_id": incident_id})
    )
    assert meta["total_count"] == 0, (
        "a rejected booking must persist no interview, found "
        f"{meta['total_count']}"
    )
    assert rows == [], f"expected no interviews on the incident, got {rows}"


def test_team_member_listing_reports_window_and_total_count(api):
    """PRD §2.3: "`limit` defaults to 10 when omitted, may be no smaller than 1 and
    no larger than 100. `offset` defaults to 0 and may be no smaller than 0 ... The
    `meta` block of a list response carries `limit` and `offset` echoing the
    effective values used, `total_count` giving the number of records matching the
    filters before the page window is applied, and `has_more` indicating whether
    any matching record remains beyond the current window."

    Design: Corner/entities/corner_team_member_listing_returns_pagination_envelope
    """
    admin_headers = make_program_admin_headers()
    first = register_member(full_name="Dana Ruiz", org_title="VP Operations")
    second = register_member(full_name="Ivo Berg", org_title="Comms Director")
    third = register_member(full_name="Ray Lund", org_title="Social Analyst")

    page_one, meta_one = validate_paginated(
        api.list_team_members(admin_headers, {"limit": 2, "offset": 0})
    )
    assert meta_one["limit"] == 2, f"meta.limit must echo 2, got {meta_one['limit']}"
    assert meta_one["offset"] == 0, f"meta.offset must echo 0, got {meta_one['offset']}"
    assert meta_one["total_count"] == 3, (
        f"meta.total_count must count all three rows, got {meta_one['total_count']}"
    )
    assert meta_one["has_more"] is True, "a further row remains beyond the window"
    assert len(page_one) == 2, f"expected two items on the first page, got {len(page_one)}"

    page_two, meta_two = validate_paginated(
        api.list_team_members(admin_headers, {"limit": 2, "offset": 2})
    )
    assert meta_two["offset"] == 2, f"meta.offset must echo 2, got {meta_two['offset']}"
    assert meta_two["total_count"] == 3, (
        f"meta.total_count must ignore the window, got {meta_two['total_count']}"
    )
    assert meta_two["has_more"] is False, "no row remains beyond the second window"
    assert len(page_two) == 1, f"expected one item on the second page, got {len(page_two)}"

    seen = ids_of(page_one) + ids_of(page_two)
    assert sorted(seen) == sorted([first["id"], second["id"], third["id"]]), (
        f"the two pages must together carry each member exactly once, got {seen}"
    )


def test_monitoring_incident_read_back_echoes_inputs_and_leaves_severity_null(api):
    """PRD §3.3: "A new incident begins in `response_state` `MONITORING`,
    `privilege_state` `NON_PRIVILEGED`, `comms_posture` `OPEN`, with
    `legal_hold_active` false, `sla_breached` false, a null `privilege_basis`, and
    every counter — `linked_signal_count`, `escalated_signal_count`,
    `open_approval_task_count`, `blocked_notice_count`, `released_notice_count`,
    `open_claim_count`, `confirmed_interview_count` — at 0, a
    `stakeholder_reach_index` of 0.00, and nulls in `activated_at`, `resolved_at`,
    `severity_tier`, `severity_basis`, `severity_score` ... and
    `reputation_delta_reported`."

    Design: Corner/entities/corner_incident_retrieval_echoes_stored_values
    """
    scenario = setup_monitoring_incident(
        clock="2026-08-10T09:00:00Z",
        scenario_code="DATA_BREACH",
        title="Customer records exposed",
        reputation_index_before=62.40,
    )

    incident = validate_success(
        api.get_incident(scenario["incident"]["id"], scenario["headers"]["lead"])
    )

    assert_fields(
        incident,
        {
            "title": "Customer records exposed",
            "scenario_code": "DATA_BREACH",
            "response_state": "MONITORING",
            "privilege_state": "NON_PRIVILEGED",
            "comms_posture": "OPEN",
            "legal_hold_active": False,
            "sla_breached": False,
            "privilege_basis": None,
            "severity_tier": None,
            "severity_basis": None,
            "severity_score": None,
            "activated_at": None,
            "resolved_at": None,
            "holding_statement_due_at": None,
            "holding_statement_published_at": None,
        },
        "Incident",
    )
    assert_two_decimals(
        incident.get("reputation_index_before"), 62.40, "reputation_index_before"
    )
    assert_two_decimals(
        incident.get("stakeholder_reach_index"), 0.00, "stakeholder_reach_index"
    )
    for counter in (
        "linked_signal_count",
        "escalated_signal_count",
        "open_approval_task_count",
        "blocked_notice_count",
        "released_notice_count",
        "open_claim_count",
        "confirmed_interview_count",
    ):
        assert_ledger(incident, counter, 0)


def test_signal_collection_filtered_by_incident_scopes_rows_to_that_parent(api):
    """PRD §2.5: "The resource graph is deliberately **flat**. No entity is nested
    inside another entity's URL path; every collection sits directly under
    `/crisis/<collection>`, and every parent-child relationship is discovered by
    filtering a collection rather than by walking a nested path."

    Design: Corner/entities/corner_flat_topology_filtered_list_scopes_rows_by_foreign_key
    """
    scenario = setup_monitoring_incident(
        clock="2026-08-10T09:00:00Z",
        scenario_code="DATA_BREACH",
        title="First incident",
    )
    incident_a = scenario["incident"]["id"]
    incident_b = open_incident(
        scenario["headers"]["lead"],
        title="Second incident",
        scenario_code="REGULATORY_PROBE",
    )["id"]

    listener_headers = scenario["headers"]["listener"]
    linked = record_signal(
        scenario["channel"]["id"],
        listener_headers,
        headline="Signal that gets linked",
        reach_score=55,
    )
    unlinked = record_signal(
        scenario["channel"]["id"],
        listener_headers,
        headline="Signal that stays open",
        reach_score=55,
    )
    link_signal(linked["id"], incident_a, listener_headers)

    rows_a, meta_a = validate_paginated(
        api.list_issue_signals(listener_headers, {"incident_id": incident_a})
    )
    assert meta_a["total_count"] == 1, (
        f"only the linked signal belongs to the first incident, got {meta_a['total_count']}"
    )
    assert ids_of(rows_a) == [linked["id"]], (
        f"expected only the linked signal, got {ids_of(rows_a)}"
    )
    assert unlinked["id"] not in ids_of(rows_a), (
        "the unlinked signal must not appear under the first incident"
    )

    rows_b, meta_b = validate_paginated(
        api.list_issue_signals(listener_headers, {"incident_id": incident_b})
    )
    assert meta_b["total_count"] == 0, (
        f"the second incident carries no signals, got {meta_b['total_count']}"
    )
    assert rows_b == [], f"expected no signals on the second incident, got {rows_b}"

    assert_field(read_signal(linked["id"]), "incident_id", incident_a, "IssueSignal")
    assert_field(read_signal(unlinked["id"]), "incident_id", None, "IssueSignal")
