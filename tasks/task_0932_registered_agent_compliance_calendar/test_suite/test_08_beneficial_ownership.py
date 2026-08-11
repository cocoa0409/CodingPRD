"""The federal beneficial-ownership axis and its reports."""
from test_helpers import (
    AGENT,
    DE_RULE_MIN,
    OFFICER,
    ApiErrorId,
    add_owner,
    assert_boi_report,
    draft_boi_report,
    new_client,
    new_entity,
    read_entity,
    record_boi_outcome,
    set_clock,
    setup_filed_boi_entity,
    submit_boi_report,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_boi_axis_moves_while_the_lifecycle_axis_stands_still(api):
    """PRD §3.10: "Recording an `ACCEPTED` outcome on an `INITIAL` report while the axis
    is `PENDING_INITIAL` moves it to `FILED` and clears `boi_update_deadline` to null."
    PRD §3.10: "A reportable change while the axis is `FILED` moves it to `UPDATE_DUE`
    and arms `boi_update_deadline`."
    PRD §3.10: "A reportable change sets `boi_update_deadline` to the date of the change
    plus 30 calendar days and moves the axis to `UPDATE_DUE` — but only when the axis is
    currently `FILED`, `UPDATE_DUE` or `DELINQUENT`."
    PRD §3.1: "An entity carries **two state axes that evolve entirely independently of
    one another**."

    Design: Corner/state_machines/corner_boi_axis_moves_independently_of_lifecycle_axis
    """
    scene = setup_filed_boi_entity(DE_RULE_MIN, formation_date="2026-02-10")
    entity = scene["entity"]

    assert entity["boi_status"] == "FILED"
    assert entity["boi_update_deadline"] is None
    assert entity["lifecycle_status"] == "ACTIVE"
    assert_boi_report(scene["report"])
    assert scene["report"]["status"] == "ACCEPTED"
    assert scene["report"]["owner_snapshot_count"] == 1

    set_clock("2026-08-01T00:00:00Z")
    validate_success(
        api.update_beneficial_owner(
            scene["owner"]["id"], {"residential_address": "41 Quay Street"}, OFFICER
        )
    )

    after = read_entity(entity["id"])
    assert after["boi_status"] == "UPDATE_DUE"
    # The change date 2026-08-01 plus 30 calendar days is 2026-08-31.
    assert after["boi_update_deadline"] == "2026-08-31"
    assert after["lifecycle_status"] == "ACTIVE"


def test_claiming_an_exemption_suppresses_the_beneficial_ownership_obligation(api):
    """PRD §3.10: "Setting `boi_exempt_class` to a value other than `NONE` while the
    axis is `PENDING_INITIAL` moves it to `NOT_REQUIRED` and sets both
    `boi_initial_deadline` and `boi_update_deadline` to null."
    PRD §2.9: "the parent legal entity has `boi_exempt_class` `NONE`; an exempt class
    suppresses the beneficial-ownership obligation entirely. Applies to
    `POST /legal-entities/{id}/boi-reports` and `POST /boi-reports/{id}/submit`. Failure
    returns `ERR_BOI_EXEMPT_ENTITY` (HTTP 409)."

    Design: Corner/state_machines/corner_boi_exempt_class_suppresses_the_initial_deadline
    """
    client = new_client()
    entity = new_entity(client["id"], formation_date="2026-02-10")

    patched = validate_success(
        api.update_legal_entity(
            entity["id"], {"boi_exempt_class": "LARGE_OPERATING"}, OFFICER
        )
    )
    assert patched["boi_status"] == "NOT_REQUIRED"
    assert patched["boi_initial_deadline"] is None

    response = api.create_boi_report(
        entity["id"],
        {
            "report_kind": "INITIAL",
            "includes_company_applicant": True,
            "expected_legal_entity_version": patched["version"],
        },
        OFFICER,
    )

    assert response.status_code == 409
    validate_error(response, ApiErrorId.ERR_BOI_EXEMPT_ENTITY.value)

    _rows, meta = validate_paginated(api.list_boi_reports(entity["id"], OFFICER))
    assert meta["total_count"] == 0


def test_rejected_report_leaves_the_axis_exactly_where_it_stood(api):
    """PRD §3.10: "`REJECTED` moves the report to `REJECTED` and **deliberately leaves
    the entity's BOI axis exactly where it stood**, including its `boi_update_deadline`,
    so that a fresh report row can be drafted against the same unexpired deadline."

    Design: Corner/state_machines/corner_boi_report_rejection_leaves_entity_axis_unchanged
    """
    client = new_client()
    entity = new_entity(client["id"], formation_date="2026-02-10")
    add_owner(entity["id"], is_company_applicant=True)
    report = draft_boi_report(entity["id"], "INITIAL", includes_company_applicant=True)
    submit_boi_report(report["id"])

    data = record_boi_outcome(report["id"], "REJECTED")

    assert data["status"] == "REJECTED"
    assert data["accepted_on"] is None

    after = read_entity(entity["id"])
    assert after["boi_status"] == "PENDING_INITIAL"
    # Formation 2026-02-10 sits in the 30-day band: 2026-02-10 + 30 days = 2026-03-12.
    assert after["boi_initial_deadline"] == "2026-03-12"


def test_three_formation_bands_pin_three_different_initial_deadlines(api):
    """PRD §3.10: "Otherwise there are three bands, and both band comparisons are
    strict: an entity formed strictly before `2024-01-01` gets the fixed deadline
    `2025-01-01`, shared by every legacy entity regardless of when it was formed; an
    entity formed on or after `2024-01-01` but strictly before `2025-01-01` gets
    `formation_date` plus 90 calendar days; and an entity formed on or after
    `2025-01-01` gets `formation_date` plus 30 calendar days."
    PRD §3.1: "At creation the server also derives `company_applicant_required`, which
    is true exactly when `formation_date` falls on or after the company-applicant
    cutover date of `2024-01-01` and false otherwise, and derives the entity's initial
    beneficial-ownership deadline."

    Design: Corner/calculations/corner_boi_initial_deadline_three_formation_bands
    """
    client = new_client()

    legacy = new_entity(
        client["id"], legal_name="Legacy Widgets LLC", formation_date="2023-06-15"
    )
    mid = new_entity(
        client["id"], legal_name="Mid Widgets LLC", formation_date="2024-06-15"
    )
    recent = new_entity(
        client["id"], legal_name="New Widgets LLC", formation_date="2026-02-10"
    )

    assert legacy["boi_initial_deadline"] == "2025-01-01"
    assert legacy["company_applicant_required"] is False
    # 2024-06-15 plus 90 calendar days: 15 to 06-30, 31 to 07-31, 31 to 08-31, then
    # 13 more into September gives 2024-09-13.
    assert mid["boi_initial_deadline"] == "2024-09-13"
    assert mid["company_applicant_required"] is True
    # 2026-02-10 plus 30 calendar days is 2026-03-12.
    assert recent["boi_initial_deadline"] == "2026-03-12"
    assert recent["company_applicant_required"] is True


def test_post_cutover_entity_must_include_its_company_applicant(api):
    """PRD §3.10: "and when the entity's `company_applicant_required` is true,
    `includes_company_applicant` must be true, else `ERR_COMPANY_APPLICANT_REQUIRED`."
    PRD §3.10: "its `deadline_date` pinned from the entity's `boi_initial_deadline` for
    an `INITIAL` report or from `boi_update_deadline` for an `UPDATED` one, its
    `triggering_change_date` set to the date of the reportable change that armed the
    current update clock on an `UPDATED` report and null on an `INITIAL` one, and its
    `owner_snapshot_count` set to the number of the entity's beneficial owners whose
    `owner_status` is `ACTIVE` at that instant."

    Design: Corner/validations/corner_company_applicant_details_required_for_post_cutover_entity
    """
    client = new_client()
    entity = new_entity(client["id"], formation_date="2026-02-10")
    add_owner(entity["id"])
    report = draft_boi_report(entity["id"], "INITIAL", includes_company_applicant=False)

    response = api.submit_boi_report(report["id"], AGENT)

    assert response.status_code == 422
    validate_error(response, ApiErrorId.ERR_COMPANY_APPLICANT_REQUIRED.value)

    assert read_entity(entity["id"])["company_applicant_required"] is True
    rows, _meta = validate_paginated(api.list_boi_reports(entity["id"], OFFICER))
    stored = [row for row in rows if row["id"] == report["id"]][0]
    assert stored["status"] == "DRAFT"
    assert stored["deadline_date"] == "2026-03-12"
