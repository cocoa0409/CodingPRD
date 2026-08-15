"""Corner queue: entities — creation, required fields, type constraints,
not-found, immutability, FK references, system/computed fields (PRD §2.5,
§2.8, §3.1, §3.2).
"""
from test_helpers import (
    validate_success, validate_error, get_success_data, ApiErrorId,
    is_valid_uuid, NON_EXISTENT_UUID, CLOCK_DEFAULT_ISO,
    TEST_USERS, create_member, set_clock, intake_case,
)

ADMIN = TEST_USERS["platform_admin_headers"]
INTAKE = TEST_USERS["intake_specialist_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]


def test_member_creation_defaults_and_system_fields(api):
    """PRD §3.1: "The member's `enrollment_status` is system-managed, begins as `ACTIVE`,
    and may move to `DISENROLLED` or `DECEASED` over the life of the
    record."
PRD §3.1: "Two counters are computed rather than stored by clients:
    `open_case_count`, the number of the member's cases whose `status` is
    any of `RECEIVED`, `TRIAGED`, `IN_REVIEW`, `PENDING_CLINICAL`,
    `DECIDED`, `NOTIFIED`, `IRE_REFERRED`, or `REOPENED`; and
    `ctm_linked_case_count`, the number of the member's CTM-linked cases
    not yet in `CLOSED` or `WITHDRAWN`."
PRD §2.5: "**`id` (string):** A unique, server-minted identifier formatted as a UUID,
    with no type prefix."

    Design: Corner/entities/member_creation_required_fields_and_defaults
    """
    data = validate_success(api.create_member(
        {"member_ref": "MBR-EN1", "full_name": "Lena Moth",
         "program": "MEDI_CAL"}, ADMIN), expected_status=201)
    assert data["enrollment_status"] == "ACTIVE"
    assert data["open_case_count"] == 0
    assert data["ctm_linked_case_count"] == 0
    assert is_valid_uuid(data["id"]), "id must be a bare UUID"
    assert data["version"] == 1
    fetched = validate_success(api.get_member(data["id"], ADMIN))
    assert fetched["enrollment_status"] == "ACTIVE"
    assert fetched["open_case_count"] == 0


def test_member_missing_member_ref_rejected(api):
    """PRD §2.8: "A malformed payload — a missing required field, a wrong type, or an enum
    value outside its declared constraints — is rejected with
    `ERR_VALIDATION` (HTTP 400)."
PRD §3.1: "A member is registered with a `member_ref` — the plan-internal member
    identifier, such as a HICN or MBI surrogate — which must be unique
    across the plan, non-empty, and between 1 and 64 characters; a
    `full_name` used in notifications; and a `program`, one of `MEDICARE`,
    `MEDI_CAL`, or `DUAL`."

    Design: Corner/entities/member_missing_required_field_returns_validation_error
    """
    validate_error(
        api.create_member({"full_name": "No Ref", "program": "MEDICARE"},
                          ADMIN),
        ApiErrorId.ERR_VALIDATION)


def test_member_invalid_program_enum_rejected(api):
    """PRD §3.1: "A member is registered with a `member_ref` — the plan-internal member
    identifier, such as a HICN or MBI surrogate — which must be unique
    across the plan, non-empty, and between 1 and 64 characters; a
    `full_name` used in notifications; and a `program`, one of `MEDICARE`,
    `MEDI_CAL`, or `DUAL`."
PRD §2.8: "A malformed payload — a missing required field, a wrong type, or an enum
    value outside its declared constraints — is rejected with
    `ERR_VALIDATION` (HTTP 400)."

    Design: Corner/entities/member_invalid_program_enum_rejected
    """
    validate_error(
        api.create_member({"member_ref": "MBR-EN3", "full_name": "Bad Enum",
                           "program": "TRICARE"}, ADMIN),
        ApiErrorId.ERR_VALIDATION)


def test_provider_npi_must_be_exactly_ten_digits(api):
    """PRD §3.1: "A provider is registered with an `npi` — exactly 10 digits and unique — a
    `legal_name`, a `contract_status` of `CONTRACTED` or `NON_CONTRACTED`,
    and a `w9_on_file` flag that defaults to `false`."
PRD §2.8: "A malformed payload — a missing required field, a wrong type, or an enum
    value outside its declared constraints — is rejected with
    `ERR_VALIDATION` (HTTP 400)."

    Design: Corner/entities/provider_npi_format_constraint
    """
    validate_error(
        api.create_provider({"npi": "123456789", "legal_name": "Short NPI",
                             "contract_status": "CONTRACTED"}, ADMIN),
        ApiErrorId.ERR_VALIDATION)


def test_member_not_found_returns_404(api):
    """PRD §2.8: "Third, path-identifier existence, validated left to right along the URL:
    the first identifier that does not correspond to an existing row —
    whether case, notification, clinical review, IRE referral,
    effectuation, reopening, member, or provider — is rejected with
    `ERR_NOT_FOUND` (HTTP 404) before any deeper identifier is examined."

    Design: Corner/entities/member_not_found_returns_404
    """
    validate_error(api.get_member(NON_EXISTENT_UUID, ADMIN),
                   ApiErrorId.ERR_NOT_FOUND)


def test_case_event_is_append_only_snapshot(api):
    """PRD §2.5: "A `CaseEvent` and an `AuditUniverseRecord` each receive an `id` and a
    `created_at` and nothing more: both `updated_at` and `version` are
    absent on these two resources."
PRD §3.9: "Staff in the `IntakeSpecialist`, `CaseAnalyst`, `MemberServicesRep`, and
    `ComplianceOfficer` roles may append events with an `event_type` of
    `NOTE`, `DOCUMENT`, `EXTENSION_REQUEST`, `CTM_LINKED`, or
    `CTM_UNLINKED` and an optional free-text `body`; the server stamps
    `occurred_at` and captures `actor_role` and `actor_id` from the
    request headers at append time, and every append increments the parent
    case's `version` by one."

    Design: Corner/entities/case_event_immutable_no_version_field
    """
    member = create_member("MBR-EN6", full_name="Mo Na", program="MEDICARE")
    set_clock(CLOCK_DEFAULT_ISO)
    case = intake_case(member["id"], case_kind="GRIEVANCE")
    data = validate_success(api.append_case_event(
        case["id"], {"event_type": "NOTE", "body": "hello"}, INTAKE),
        expected_status=201)
    for field in ("id", "created_at", "occurred_at", "actor_role",
                  "actor_id", "event_type", "body"):
        assert field in data, f"CaseEvent must carry {field}"
    assert data["event_type"] == "NOTE"
    assert data["body"] == "hello"
    assert data["actor_role"] == "IntakeSpecialist"
    assert "version" not in data, "CaseEvent must not carry version"
    assert "updated_at" not in data, "CaseEvent must not carry updated_at"


def test_case_intake_with_missing_member_fk_rejected(api):
    """PRD §2.8: "Fourth, body references: any foreign key supplied in the payload
    (`member_id`, `provider_id`, `case_id`, `referral_id`,
    `reopened_from_case_id`) that points at a missing row is rejected with
    `ERR_REFERENCE_NOT_FOUND` (HTTP 422)."

    Design: Corner/entities/fk_reference_to_missing_member_rejected
    """
    set_clock(CLOCK_DEFAULT_ISO)
    validate_error(
        api.create_case({"member_id": NON_EXISTENT_UUID,
                         "case_kind": "GRIEVANCE"}, INTAKE),
        ApiErrorId.ERR_REFERENCE_NOT_FOUND)


def test_system_fields_in_create_payload_are_ignored(api):
    """PRD §2.5: "**`id` (string):** A unique, server-minted identifier formatted as a UUID,
    with no type prefix."
PRD §2.5: "**`version` (integer):** A system-managed integer that increments with
    every modification to the resource — including appends to its event
    log and automatic state reconciliations — and serves as the basis for
    optimistic concurrency control where §2.7 applies."

    Design: Corner/entities/system_fields_in_input_ignored
    """
    supplied_id = "11111111-2222-3333-4444-555555555555"
    data = validate_success(api.create_member(
        {"member_ref": "MBR-EN8", "full_name": "Sys Fields", "program": "DUAL",
         "id": supplied_id, "version": 99}, ADMIN), expected_status=201)
    assert data["id"] != supplied_id, "Server must mint its own id"
    assert data["version"] == 1, "Server must mint its own version"


def test_case_overdue_input_ignored_and_computed(api):
    """PRD §3.3: "A case's `overdue` flag is true whenever the current time is past
    `resolution_due_at` while the case's `status` is anything other than
    `CLOSED`, `WITHDRAWN`, or `IRE_REFERRED`."
PRD §3.2: "An `IntakeSpecialist` opens a case by supplying the `member_id` of the
    owning member, a `case_kind` of `GRIEVANCE`, `ORG_DETERMINATION`, or
    `APPEAL`, and optionally a `provider_id` naming the rendering provider
    or provider of record."

    Design: Corner/entities/case_computed_overdue_input_ignored
    """
    member = create_member("MBR-EN9", full_name="Ov Due", program="MEDICARE")
    set_clock(CLOCK_DEFAULT_ISO)
    data = validate_success(api.create_case(
        {"member_id": member["id"], "case_kind": "GRIEVANCE",
         "overdue": True}, INTAKE), expected_status=201)
    # A RECEIVED case has no resolution_due_at yet, so nothing is past due.
    assert data["overdue"] is False
