"""Optimistic concurrency on parent versions, and version arithmetic."""
from test_helpers import (
    ADMIN,
    DE_RULE_MIN,
    OFFICER,
    ApiErrorId,
    add_owner,
    draft_obligation_filing,
    new_client,
    new_entity,
    new_obligation,
    read_entity,
    read_obligation,
    setup_pending_home_registration,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_stale_obligation_version_blocks_a_second_filing_draft(api):
    """PRD §2.8: "A request to `POST /compliance-obligations/{id}/filings` must carry
    `expected_compliance_obligation_version` matching the addressed
    `ComplianceObligation`'s current `version`."
    PRD §2.8: "If the supplied value does not equal the parent's current `version`, the
    write is rejected with `ERR_STALE_VERSION` and HTTP 412, and no row is created."
    PRD §3.7: "Before the fee breakdown is computed, the obligation's `late_fee_cents`
    and `total_due_cents` are recomputed at the current clock date and the obligation's
    `version` increases by 1 — which is exactly why the caller had to prove it was
    holding a current view."

    Design: Corner/cross_cutting_complexity_layers/corner_occ_stale_obligation_version_rejects_second_filing_create
    """
    scene = setup_pending_home_registration(DE_RULE_MIN)
    obligation = new_obligation(scene["registration"]["id"], "ANNUAL_REPORT", 2027)
    stale_version = obligation["version"]
    draft_obligation_filing(obligation, "ANNUAL_REPORT")

    response = api.create_obligation_filing(
        obligation["id"],
        {
            "filing_kind": "ANNUAL_REPORT",
            "expected_compliance_obligation_version": stale_version,
        },
        OFFICER,
    )

    assert response.status_code == 412
    validate_error(response, ApiErrorId.ERR_STALE_VERSION.value)

    _rows, meta = validate_paginated(
        api.list_filings(ADMIN, params={"compliance_obligation_id": obligation["id"]})
    )
    assert meta["total_count"] == 1
    assert read_obligation(obligation["id"])["version"] == stale_version + 1


def test_stale_registration_version_blocks_a_second_appointment(api):
    """PRD §2.8: "A request to `POST /registrations/{id}/agent-appointments` must carry
    `expected_registration_version` matching the addressed `Registration`'s current
    `version`."
    PRD §3.3: "The new appointment is created in status `PROPOSED` with
    `superseded_by_appointment_id` null, `resignation_noticed_on` null,
    `resignation_effective_on` null and `of_record` false, and the parent registration's
    `version` increases by 1. A stale `expected_registration_version` is rejected with
    `ERR_STALE_VERSION` before anything is created."

    Design: Corner/cross_cutting_complexity_layers/corner_occ_stale_registration_version_rejects_second_appointment_create
    """
    scene = setup_pending_home_registration(DE_RULE_MIN)
    registration = scene["registration"]
    stale_version = registration["version"]
    first = validate_success(
        api.create_agent_appointment(
            registration["id"],
            {
                "provider_name": "Bay State Agents",
                "appointed_on": "2026-05-01",
                "expected_registration_version": stale_version,
            },
            OFFICER,
        ),
        201,
    )

    response = api.create_agent_appointment(
        registration["id"],
        {
            "provider_name": "Keystone Agent Services",
            "appointed_on": "2026-05-02",
            "expected_registration_version": stale_version,
        },
        OFFICER,
    )

    assert response.status_code == 412
    validate_error(response, ApiErrorId.ERR_STALE_VERSION.value)

    rows, meta = validate_paginated(
        api.list_agent_appointments(ADMIN, params={"registration_id": registration["id"]})
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == first["id"]


def test_stale_entity_version_blocks_a_second_boi_report(api):
    """PRD §2.8: "A request to `POST /legal-entities/{id}/boi-reports` must carry
    `expected_legal_entity_version` matching the addressed `LegalEntity`'s current
    `version`."
    PRD §3.10: "On success the report is created in `DRAFT` with `submitted_on` and
    `accepted_on` null, its `deadline_date` pinned from the entity's
    `boi_initial_deadline` for an `INITIAL` report or from `boi_update_deadline` for an
    `UPDATED` one, its `triggering_change_date` set to the date of the reportable change
    that armed the current update clock on an `UPDATED` report and null on an `INITIAL`
    one, and its `owner_snapshot_count` set to the number of the entity's beneficial
    owners whose `owner_status` is `ACTIVE` at that instant. The entity's `version`
    increases by 1."

    Design: Corner/cross_cutting_complexity_layers/corner_occ_stale_entity_version_rejects_second_boi_report_create
    """
    client = new_client()
    entity = new_entity(client["id"], formation_date="2026-02-10")
    add_owner(entity["id"], is_company_applicant=True)
    stale_version = read_entity(entity["id"])["version"]
    first = validate_success(
        api.create_boi_report(
            entity["id"],
            {
                "report_kind": "INITIAL",
                "includes_company_applicant": True,
                "expected_legal_entity_version": stale_version,
            },
            OFFICER,
        ),
        201,
    )

    response = api.create_boi_report(
        entity["id"],
        {
            "report_kind": "INITIAL",
            "includes_company_applicant": True,
            "expected_legal_entity_version": stale_version,
        },
        OFFICER,
    )

    assert response.status_code == 412
    validate_error(response, ApiErrorId.ERR_STALE_VERSION.value)

    rows, meta = validate_paginated(api.list_boi_reports(entity["id"], OFFICER))
    assert meta["total_count"] == 1
    assert rows[0]["id"] == first["id"]


def test_version_advances_by_one_per_mutation_and_never_on_a_read(api):
    """PRD §2.4: "`version` is an integer that starts at 1 when the row is created and
    increases by exactly 1 on every mutation of that row, including mutations the row
    undergoes as a side effect of an operation addressed at some other resource."
    PRD §3.1: "Any accepted update increases the entity's `version` by 1."

    Design: Corner/cross_cutting_complexity_layers/corner_version_increments_by_one_on_every_mutation
    """
    client = new_client()
    entity = new_entity(client["id"])
    assert entity["version"] == 1

    first_patch = validate_success(
        api.update_legal_entity(entity["id"], {"authorized_shares": 8000}, OFFICER)
    )
    assert first_patch["version"] == 2

    assert read_entity(entity["id"])["version"] == 2, "a plain read never advances it"

    second_patch = validate_success(
        api.update_legal_entity(entity["id"], {"issued_shares": 4000}, OFFICER)
    )
    assert second_patch["version"] == 3
    assert second_patch["authorized_shares"] == 8000
    assert second_patch["issued_shares"] == 4000
