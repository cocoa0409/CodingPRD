"""Access control and request-gate ordering: missing credentials, wrong-role
denials, shape-before-role ordering, body foreign-key existence, entity-backed
ownership (positive and negative), exclusive-operation denials, and the
uniqueness invariants."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    NO_AUTH_HEADERS,
    begin_screening,
    create_complaint_payload,
    create_complainant,
    create_event,
    create_fund,
    create_fund_payload,
    create_monitor,
    create_monitor_payload,
    create_operator,
    create_operator_payload,
    create_report,
    make_complainant_headers,
    make_operator_rep_headers,
    make_study_coordinator_headers,
    TEST_USERS,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["noise_office_admin_headers"]
ANALYST = TEST_USERS["noise_analyst_headers"]
LIAISON = TEST_USERS["community_liaison_headers"]
BOARD = TEST_USERS["board_member_headers"]


def test_request_missing_auth_headers_returns_unauthenticated(api):
    """PRD 2.1: "A request missing either header, or carrying a role the system
    does not declare, is rejected with `ERR_UNAUTHENTICATED`."
    PRD 2.11: "1. **Presence of credentials** — both `X-User-ID` and
    `X-User-Role` headers are present and the role is one of the seven declared
    roles, else `ERR_UNAUTHENTICATED`."

    Design: Corner/validations/request_missing_auth_headers_returns_unauthenticated
    """
    response = api.list_operators(NO_AUTH_HEADERS)
    validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED)


def test_wrong_role_with_valid_payload_returns_unauthorized(api):
    """PRD 2.1: "Access to each operation is restricted by role; an attempt to
    perform an action outside the caller's designated role is rejected with
    `ERR_UNAUTHORIZED_ROLE`."

    Design: Corner/validations/wrong_role_with_valid_payload_returns_unauthorized
    """
    # Operator registration is the NoiseOfficeAdmin's exclusive operation; the
    # body is fully valid, so only the role gate can fail.
    response = api.create_operator(
        create_operator_payload(name="Rogue Air", iata_code="RA"), ANALYST
    )
    validate_error(response, ApiErrorId.ERR_UNAUTHORIZED_ROLE)


def test_shape_violation_invalid_payload_beats_role_check(api):
    """PRD 2.11: "Every request is checked against a fixed sequence of gates,
    and the first gate that fails determines the error returned; later gates are
    not evaluated for that request. The ordering is deliberate — authentication
    outranks shape, shape outranks authorization, existence outranks state, and
    fiscal guards are evaluated last".
    PRD 2.11: "2. **Request shape** — required fields are present, types and
    enum members are valid ... Failures are rejected with `ERR_VALIDATION`."

    Design: Corner/validations/shape_violation_invalid_payload_beats_role_check
    """
    # BoardMember lacks the role for operator registration, but the missing
    # iata_code (shape, gate 2) is reported before the role check (gate 3).
    response = api.create_operator(
        {"name": "Broken Air", "contact_email": "ops@broken.example"}, BOARD
    )
    validate_error(response, ApiErrorId.ERR_VALIDATION)


def test_complaint_create_with_unknown_complainant_returns_not_found(api):
    """PRD 3.4: "A `complainant_id` that does not resolve is rejected with
    `ERR_COMPLAINANT_NOT_FOUND`".
    PRD 2.11: "7. **Body foreign-key existence** — a `complainant_id` in the
    body must resolve (else `ERR_COMPLAINANT_NOT_FOUND`)".

    Design: Corner/validations/complaint_create_with_unknown_complainant_returns_not_found
    """
    # A CommunityLiaison files on behalf: the body's complainant FK misses.
    response = api.create_complaint(
        create_complaint_payload(NON_EXISTENT_UUID, occurred_at="2026-07-15T09:00:00Z"),
        LIAISON,
    )
    validate_error(response, ApiErrorId.ERR_COMPLAINANT_NOT_FOUND)


def test_uniqueness_constraint_violations_rejected(api):
    """PRD 3.1: "The `iata_code` is unique across all operators; a duplicate
    registration is rejected with `ERR_DUPLICATE_IATA_CODE`."
    PRD 3.3: "A `NoiseOfficeAdmin` registers each **NoiseMonitor** with a unique
    `station_code` (a duplicate is rejected with `ERR_DUPLICATE_STATION_CODE`)".
    PRD 3.8: "a `fiscal_year` label such as FY2026 — unique across all funds,
    with duplicates rejected as `ERR_DUPLICATE_FISCAL_YEAR_FUND`" and "At most
    one fund may be `ACTIVE` at a time: creating a second while one is active is
    rejected with `ERR_ACTIVE_FUND_EXISTS`."
    PRD 3.9: "a `quarter_label` in the `YYYY-Qn` format — unique across all
    reports, with duplicates rejected as `ERR_DUPLICATE_QUARTER_REPORT`".

    Design: Corner/validations/uniqueness_constraint_violations_rejected
    """
    create_operator(name="Air Uniq", iata_code="AU")
    dup_operator = api.create_operator(
        create_operator_payload(name="Air Uniq2", iata_code="AU"), ADMIN
    )
    validate_error(dup_operator, ApiErrorId.ERR_DUPLICATE_IATA_CODE)

    create_monitor(station_code="ST-1")
    dup_monitor = api.create_monitor(
        create_monitor_payload(station_code="ST-1", zone_code="Z2"), ADMIN
    )
    validate_error(dup_monitor, ApiErrorId.ERR_DUPLICATE_STATION_CODE)

    fund = create_fund(fiscal_year="FY2027", total_allocation_cents=5_000_000)
    # A distinct fiscal year while one fund is ACTIVE: only the single-ACTIVE
    # guard can fail.
    second_active = api.create_fund(
        create_fund_payload(
            fiscal_year="FY2028",
            total_allocation_cents=1_000_000,
            intake_opens_at="2026-10-01T00:00:00Z",
            intake_closes_at="2026-12-31T00:00:00Z",
        ),
        ADMIN,
    )
    validate_error(second_active, ApiErrorId.ERR_ACTIVE_FUND_EXISTS)

    # With the first fund closed (no reservations), a repeated fiscal year
    # isolates the duplicate-fiscal-year guard.
    validate_success(api.close_fund(fund["id"], {}, ADMIN), 200)
    dup_fiscal_year = api.create_fund(
        create_fund_payload(fiscal_year="FY2027", total_allocation_cents=1_000_000),
        ADMIN,
    )
    validate_error(dup_fiscal_year, ApiErrorId.ERR_DUPLICATE_FISCAL_YEAR_FUND)

    create_report(quarter_label="2026-Q2")
    dup_report = api.create_report({"quarter_label": "2026-Q2"}, ANALYST)
    validate_error(dup_report, ApiErrorId.ERR_DUPLICATE_QUARTER_REPORT)


def test_entity_backed_ownership_violations_forbidden(api):
    """PRD 2.1: "An entity-backed caller acting on a resource it does not own is
    rejected with `ERR_NOT_RESOURCE_OWNER`."
    PRD 3.1: "Staff can read any complainant record; a `Complainant` caller may
    read only the record whose `id` equals their `X-User-ID`."
    PRD 3.5: "Acting on another operator's notification is rejected with
    `ERR_NOT_RESOURCE_OWNER`".

    Design: Corner/errors/entity_backed_ownership_violations_forbidden
    """
    owner_a = create_complainant(full_name="Own A", email="owna@x.com")
    owner_b = create_complainant(full_name="Own B", email="ownb@x.com")
    operator_x = create_operator(name="Air X")
    operator_y = create_operator(name="Air Y")
    complaint = validate_success(
        api.create_complaint(
            create_complaint_payload(owner_b["id"], occurred_at="2026-07-15T09:00:00Z"),
            make_complainant_headers(owner_b["id"]),
        ),
        201,
    )
    notification = validate_success(
        api.create_notification(
            {
                "operator_id": operator_y["id"],
                "complaint_id": complaint["id"],
                "severity": "FORMAL",
                "subject": "Own test",
                "body": "Ownership test body.",
            },
            ANALYST,
        ),
        201,
    )
    validate_success(api.send_notification(notification["id"], {}, ANALYST), 200)

    # Complainant A reading complainant B's record.
    wrong_owner = api.get_complainant(owner_b["id"], make_complainant_headers(owner_a["id"]))
    validate_error(wrong_owner, ApiErrorId.ERR_NOT_RESOURCE_OWNER)

    # OperatorRep X acknowledging operator Y's notification.
    wrong_operator = api.acknowledge_notification(
        notification["id"], {}, make_operator_rep_headers(operator_x["id"])
    )
    validate_error(wrong_operator, ApiErrorId.ERR_NOT_RESOURCE_OWNER)


def test_rbac_entity_backed_positive_reads(api):
    """PRD 2.1: "When `X-User-Role` is `OperatorRep`, `X-User-ID` is the `id` of
    the acting Operator" and "When `X-User-Role` is `Complainant`, `X-User-ID`
    is the `id` of the acting Complainant".
    PRD 3.2: "An `OperatorRep` caller may request only their own operator's
    summary, may read only their own operator record".

    Design: Corner/rbac/rbac_entity_backed_positive_reads
    """
    operator = create_operator(name="Air Pos")
    complainant = create_complainant(full_name="Pos One", email="pos1@x.com")

    own_operator = validate_success(
        api.get_operator(operator["id"], make_operator_rep_headers(operator["id"]))
    )
    assert own_operator["name"] == "Air Pos"

    own_record = validate_success(
        api.get_complainant(complainant["id"], make_complainant_headers(complainant["id"]))
    )
    assert own_record["full_name"] == "Pos One"


def test_rbac_exclusive_operation_denials(api):
    """PRD 2.1: "Access to each operation is restricted by role; an attempt to
    perform an action outside the caller's designated role is rejected with
    `ERR_UNAUTHORIZED_ROLE`."
    PRD 2.11: "3. **Role authorization** — the caller's role appears in the
    endpoint's authorized role list, else `ERR_UNAUTHORIZED_ROLE`."

    Design: Corner/rbac/rbac_exclusive_operation_denials
    """
    monitor = create_monitor(station_code="RB1")
    event = create_event(monitor["id"])
    begin_screening(event["id"])
    report = create_report(quarter_label="2026-Q2")
    validate_success(api.submit_for_review(report["id"], {}, ANALYST), 200)
    complainant = create_complainant(full_name="RB One", email="rb1@x.com")

    # Monitor registration is NoiseOfficeAdmin-only (PRD 4): BoardMember denied.
    deny_monitor = api.create_monitor(
        create_monitor_payload(station_code="RB2", zone_code="Z2"), BOARD
    )
    validate_error(deny_monitor, ApiErrorId.ERR_UNAUTHORIZED_ROLE)

    # Report approval is BoardMember-only: StudyCoordinator denied.
    deny_approve = api.approve_report(
        report["id"], {}, make_study_coordinator_headers("study-1")
    )
    validate_error(deny_approve, ApiErrorId.ERR_UNAUTHORIZED_ROLE)

    # Complaint filing is Complainant/CommunityLiaison-only: OperatorRep denied.
    deny_complaint = api.create_complaint(
        create_complaint_payload(complainant["id"], occurred_at="2026-07-15T09:00:00Z"),
        TEST_USERS["operator_rep_headers"],
    )
    validate_error(deny_complaint, ApiErrorId.ERR_UNAUTHORIZED_ROLE)

    # Event classification is NoiseAnalyst-only: CommunityLiaison denied.
    deny_classify = api.classify_event(
        event["id"], {"classification": "COMMUNITY"}, LIAISON
    )
    validate_error(deny_classify, ApiErrorId.ERR_UNAUTHORIZED_ROLE)

    # Sanity: the denied mutations left no trace.
    reread_report = validate_success(api.get_report(report["id"], ANALYST))
    assert reread_report["status"] == "UNDER_REVIEW"
    reread_event = validate_success(api.get_event(event["id"], ANALYST))
    assert reread_event["status"] == "SCREENING"
