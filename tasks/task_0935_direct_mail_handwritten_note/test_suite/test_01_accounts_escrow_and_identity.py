"""Mailer accounts, the permit escrow ledger, request shape and caller identity."""

from test_helpers import (
    ApiErrorId,
    CAMPAIGN_MANAGER,
    LIST_OPERATOR,
    NON_EXISTENT_UUID,
    PLATFORM_ADMIN,
    PRODUCTION_OPERATOR,
    account_payload,
    assert_account,
    assert_append_only_fields,
    assert_campaign,
    assert_ledger_entry,
    build_addressed_scenario,
    create_account,
    create_campaign,
    create_handwriting_style,
    handwriting_style_payload,
    make_account_owner_headers,
    headers_without_role,
    headers_without_user_id,
    set_clock,
    template_payload,
    topup,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_new_account_starts_with_zero_escrow_and_zero_lifetime_counters(api):
    """PRD §3.1: "A freshly registered account starts with `permit_balance_cents`
    at 0 and all four lifetime counters — `lifetime_topup_cents`,
    `lifetime_draw_cents`, `lifetime_refund_cents`, `lifetime_forfeit_cents` — at
    0 as well."
    PRD §3.1: "Registration takes the customer's `name` and the USPS
    `permit_number` under which their mail will be entered, and optionally an
    initial `status` — one of `ACTIVE` or `SUSPENDED`, defaulting to `ACTIVE`
    when omitted."

    Design: Corner/entities/account_creation_starts_with_zero_permit_balance
    """
    set_clock()
    response = api.create_account(account_payload(permit_number="PMT-200"), PLATFORM_ADMIN)
    account = validate_success(response, 201)
    assert_account(account)

    assert account["permit_balance_cents"] == 0
    assert account["lifetime_topup_cents"] == 0
    assert account["lifetime_draw_cents"] == 0
    assert account["lifetime_refund_cents"] == 0
    assert account["lifetime_forfeit_cents"] == 0
    assert account["status"] == "ACTIVE"
    assert account["version"] == 1


def test_new_campaign_defaults_all_three_axes_and_derives_an_open_write_gate(api):
    """PRD §3.4: "It begins at `lifecycle_status` `DRAFT`, `compliance_status`
    `CLEAR`, `billing_status` `OPEN` and therefore `write_gate` `OPEN`, with
    `hold_reason` null, `mailed_piece_count` and `returned_piece_count` at 0, and
    `committed_postage_cents`, `refunded_postage_cents` and
    `forfeited_postage_cents` at 0."

    Design: Corner/entities/campaign_defaults_three_status_axes_and_open_write_gate
    """
    set_clock()
    account = create_account(permit_number="PMT-201")
    response = api.create_campaign(
        {"account_id": account["id"], "name": "Spring 2026"}, CAMPAIGN_MANAGER
    )
    campaign = validate_success(response, 201)
    assert_campaign(campaign)

    assert campaign["lifecycle_status"] == "DRAFT"
    assert campaign["compliance_status"] == "CLEAR"
    assert campaign["billing_status"] == "OPEN"
    assert campaign["write_gate"] == "OPEN"
    assert campaign["hold_reason"] is None
    assert campaign["mailed_piece_count"] == 0
    assert campaign["returned_piece_count"] == 0
    assert campaign["committed_postage_cents"] == 0
    assert campaign["refunded_postage_cents"] == 0
    assert campaign["forfeited_postage_cents"] == 0


def test_topup_ledger_row_is_append_only_and_carries_no_version(api):
    """PRD §2.4: "Three resource types are append-only records of something that
    already happened, and they carry only `id` and `created_at` — no `updated_at`
    and no `version` at all: `PostageLedgerEntry`, `ReturnEvent` and
    `BlackoutDate`."
    PRD §3.1: "The top-up appends a `TOPUP` ledger entry with both `campaign_id`
    and `mail_job_id` left null, raises `permit_balance_cents` and
    `lifetime_topup_cents` by `amount_cents`, and increments the account's
    `version` by one."

    Design: Corner/entities/postage_ledger_entry_is_append_only_without_version
    """
    set_clock()
    account = create_account(permit_number="PMT-206")
    topup(account["id"], 500_000)

    response = api.list_postage_ledger_entries(
        PLATFORM_ADMIN, params={"account_id": account["id"], "entry_type": "TOPUP"}
    )
    rows, meta = validate_paginated(response)

    assert len(rows) == 1, "one TOPUP row was appended"
    row = rows[0]
    assert_ledger_entry(row)
    assert_append_only_fields(row, "PostageLedgerEntry")

    assert row["entry_type"] == "TOPUP"
    assert row["amount_cents"] == 500_000
    assert row["signed_amount_cents"] == 500_000
    assert row["balance_after_cents"] == 500_000
    assert row["campaign_id"] is None
    assert row["mail_job_id"] is None
    assert meta["total_count"] == 1


def test_topup_against_a_missing_account_reports_the_account_not_found_code(api):
    """PRD §2.6: "The rejection is `ERR_ACCOUNT_NOT_FOUND` when an account
    reference dangles, `ERR_CAMPAIGN_NOT_FOUND` for a campaign reference,
    `ERR_MAIL_JOB_NOT_FOUND` for a mail-job reference, and
    `ERR_RESOURCE_NOT_FOUND` for every other resource type."

    Design: Corner/entities/account_not_found_on_postage_topup
    """
    set_clock()
    response = api.create_postage_topup(
        NON_EXISTENT_UUID, {"amount_cents": 1000, "reason": "seed"}, PLATFORM_ADMIN
    )
    validate_error(response, ApiErrorId.ERR_ACCOUNT_NOT_FOUND.value)

    rows = api.list_postage_ledger_entries(PLATFORM_ADMIN, params={"limit": 100})
    data, _ = validate_paginated(rows)
    assert data == [], "a rejected top-up writes no ledger row"


def test_estimate_on_a_missing_job_reports_the_mail_job_not_found_code(api):
    """PRD §2.11: "an unresolvable account reference is `ERR_ACCOUNT_NOT_FOUND`, a
    campaign reference is `ERR_CAMPAIGN_NOT_FOUND`, a mail-job reference is
    `ERR_MAIL_JOB_NOT_FOUND`, and every other type — mailing list, list record,
    template, handwriting style, proof, production run, writing machine, ink lot,
    EDDM route selection, drip schedule, drip step, return event, reprint request,
    ledger row, blackout date — is `ERR_RESOURCE_NOT_FOUND`."

    Design: Corner/entities/mail_job_not_found_on_estimate
    """
    set_clock()
    response = api.estimate_mail_job(NON_EXISTENT_UUID, CAMPAIGN_MANAGER)
    validate_error(response, ApiErrorId.ERR_MAIL_JOB_NOT_FOUND.value)


def test_activating_a_missing_campaign_reports_the_campaign_not_found_code(api):
    """PRD §2.11: "an unresolvable account reference is `ERR_ACCOUNT_NOT_FOUND`, a
    campaign reference is `ERR_CAMPAIGN_NOT_FOUND`, a mail-job reference is
    `ERR_MAIL_JOB_NOT_FOUND`, and every other type — mailing list, list record,
    template, handwriting style, proof, production run, writing machine, ink lot,
    EDDM route selection, drip schedule, drip step, return event, reprint request,
    ledger row, blackout date — is `ERR_RESOURCE_NOT_FOUND`."

    Design: Corner/entities/campaign_not_found_on_activate
    """
    set_clock()
    response = api.activate_campaign(NON_EXISTENT_UUID, CAMPAIGN_MANAGER)
    validate_error(response, ApiErrorId.ERR_CAMPAIGN_NOT_FOUND.value)


def test_reading_a_missing_ink_lot_reports_the_catch_all_resource_code(api):
    """PRD §2.11: "an unresolvable account reference is `ERR_ACCOUNT_NOT_FOUND`, a
    campaign reference is `ERR_CAMPAIGN_NOT_FOUND`, a mail-job reference is
    `ERR_MAIL_JOB_NOT_FOUND`, and every other type — mailing list, list record,
    template, handwriting style, proof, production run, writing machine, ink lot,
    EDDM route selection, drip schedule, drip step, return event, reprint request,
    ledger row, blackout date — is `ERR_RESOURCE_NOT_FOUND`."

    Design: Corner/entities/resource_not_found_on_ink_lot_read
    """
    set_clock()
    response = api.get_ink_lot(NON_EXISTENT_UUID, PRODUCTION_OPERATOR)
    validate_error(response, ApiErrorId.ERR_RESOURCE_NOT_FOUND.value)


def test_template_create_without_character_count_is_a_request_shape_failure(api):
    """PRD §2.6: "Rung 6 covers request shape: a required body field that is
    absent, a field whose JSON type is wrong, or a date or datetime string that
    does not parse as ISO 8601, all answering `ERR_VALIDATION` (HTTP 400)."
    PRD §3.2: "Creating one takes the owning `account_id`, the
    `handwriting_style_id` the robot will write it in, a `name`, the `body_text`
    copy, a `character_count` giving how many characters the pen actually lays
    down per piece, and optionally an `envelope_style` of `STANDARD`, `WINDOW` or
    `HAND_ADDRESSED`, defaulting to `STANDARD`."

    Design: Corner/entities/missing_required_field_on_template_create
    """
    set_clock()
    account = create_account(permit_number="PMT-203")
    style = create_handwriting_style()

    payload = template_payload(account["id"], style["id"])
    payload.pop("character_count")
    response = api.create_template(payload, CAMPAIGN_MANAGER)
    validate_error(response, ApiErrorId.ERR_VALIDATION.value)

    listed = api.list_templates(CAMPAIGN_MANAGER, params={"account_id": account["id"]})
    data, _ = validate_paginated(listed)
    assert data == [], "a rejected create leaves no Template behind"


def test_unknown_pen_type_routes_to_the_closed_enum_rung(api):
    """PRD §2.6: "Rung 7 covers enum membership and answers `ERR_INVALID_ENUM`
    (HTTP 422), and its scope is **exhaustive and closed**: the fields that route
    here are exactly `Account.status`; the campaign lifecycle, compliance and
    billing status values when supplied as input; `pen_type` and `ink_type` on a
    handwriting style; `envelope_style` on a template; `dpv_confirmation_code` on
    a recipient record and `new_dpv_confirmation_code` on a move update;
    `job_kind`, `mail_class` and `eddm_rate_variant` on a mail job; the `mode` of
    a dedupe run; `capacity_variant` on a production run; `anchor_variant` on a
    drip schedule; `ink_type` on an ink lot; `status` on a writing machine; and
    `return_reason` on a return."

    Design: Corner/entities/invalid_enum_on_handwriting_style_pen_type
    """
    set_clock()
    payload = handwriting_style_payload(name="Odd Script", pen_type="QUILL")
    response = api.create_handwriting_style(payload, PRODUCTION_OPERATOR)

    error = validate_error(response, ApiErrorId.ERR_INVALID_ENUM.value)
    assert error["error_id"] != ApiErrorId.ERR_VALIDATION.value


def test_character_count_of_2001_breaches_the_inclusive_upper_bound(api):
    """PRD §3.2: "The character count is bounded at both ends: at least 1
    character and at most 2000, both bounds inclusive, with anything outside that
    window rejected as `ERR_VALUE_OUT_OF_RANGE`."

    Design: Corner/entities/character_count_above_maximum_rejected
    """
    set_clock()
    account = create_account(permit_number="PMT-204")
    style = create_handwriting_style()

    response = api.create_template(
        template_payload(account["id"], style["id"], name="Long Note",
                         body_text="x", character_count=2001),
        CAMPAIGN_MANAGER,
    )
    validate_error(response, ApiErrorId.ERR_VALUE_OUT_OF_RANGE.value)


def test_reusing_a_permit_number_is_refused_as_a_duplicate_key(api):
    """PRD §3.1: "Permit numbers are globally unique across accounts and must be
    non-empty; a second registration reusing a permit number already on file is
    refused with `ERR_DUPLICATE_KEY` (HTTP 409)."

    Design: Corner/validations/duplicate_permit_number_returns_duplicate_key
    """
    set_clock()
    first = create_account(permit_number="PMT-243")

    response = api.create_account(
        account_payload(name="Copycat Mailers", permit_number="PMT-243"), PLATFORM_ADMIN
    )
    validate_error(response, ApiErrorId.ERR_DUPLICATE_KEY.value)

    unchanged = validate_success(api.get_account(first["id"], PLATFORM_ADMIN))
    assert unchanged["name"] == "Northwind Mailers"


def test_a_request_with_no_role_header_is_unauthenticated_before_any_lookup(api):
    """PRD §2.1: "A request whose `X-User-Role` header is absent, or whose value
    is not one of those six strings, is rejected with `ERR_UNAUTHENTICATED`
    (HTTP 401)."
    PRD §2.6: "1. `X-User-Role` is present and names one of the six declared
    roles — otherwise `ERR_UNAUTHENTICATED`."

    Design: Corner/rbac/missing_role_header_returns_unauthenticated
    """
    set_clock()
    response = api.get_campaign(NON_EXISTENT_UUID, headers_without_role())

    error = validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED.value)
    assert error["error_id"] != ApiErrorId.ERR_CAMPAIGN_NOT_FOUND.value


def test_account_owner_without_a_user_id_header_is_unauthenticated(api):
    """PRD §2.1: "A request acting as `AccountOwner` with no `X-User-ID` header
    is likewise rejected with `ERR_UNAUTHENTICATED`."
    PRD §2.6: "2. `X-User-ID` is present whenever the caller acts as
    `AccountOwner`, the one identity-backed role — otherwise
    `ERR_UNAUTHENTICATED`."

    Design: Corner/rbac/account_owner_without_user_id_header_returns_unauthenticated
    """
    set_clock()
    account = create_account(permit_number="PMT-251")

    response = api.get_account(account["id"], headers_without_user_id("AccountOwner"))
    error = validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED.value)
    assert error["error_id"] != ApiErrorId.ERR_ACCOUNT_SCOPE_VIOLATION.value


def test_list_operator_is_forbidden_from_committing_a_mail_job(api):
    """PRD §2.1: "Once the caller is authenticated, the role must appear in the
    endpoint's authorized-role list in §4; if it does not, the response is
    `ERR_FORBIDDEN_ROLE` (HTTP 403)."
    PRD §3.7: "A `CampaignManager` or `PlatformAdmin` commits a job in
    `SCHEDULED`, moving it `SCHEDULED → COMMITTED`, and the operation prices the
    job finally, draws money from the permit escrow, and queues the physical
    pieces."

    Design: Corner/rbac/list_operator_cannot_commit_a_mail_job
    """
    bundle = build_addressed_scenario(
        permit_number="PMT-252", stage="draft", dedupe_mode=None, lock=False,
        target_in_home_date=None,
    )

    response = api.commit_mail_job(bundle["job"]["id"], LIST_OPERATOR)
    error = validate_error(response, ApiErrorId.ERR_FORBIDDEN_ROLE.value)
    assert error["error_id"] != ApiErrorId.ERR_MAIL_JOB_INVALID_STATE.value

    job = validate_success(api.get_mail_job(bundle["job"]["id"], CAMPAIGN_MANAGER))
    assert job["status"] == "DRAFT"


def test_account_owner_cannot_read_a_campaign_owned_by_another_account(api):
    """PRD §2.1: "If the resolved owner differs from `X-User-ID`, the request is
    rejected with `ERR_ACCOUNT_SCOPE_VIOLATION` (HTTP 403)."
    PRD §2.6: "5. An `AccountOwner`'s `X-User-ID` equals the account that owns
    the resolved resource — otherwise `ERR_ACCOUNT_SCOPE_VIOLATION`."

    Design: Corner/rbac/account_owner_cannot_read_another_accounts_campaign
    """
    set_clock()
    account_a = create_account(permit_number="PMT-253A", name="Account A")
    account_b = create_account(permit_number="PMT-253B", name="Account B")
    campaign_a = create_campaign(account_a["id"], name="A Spring 2026")

    response = api.get_campaign(
        campaign_a["id"], make_account_owner_headers(account_b["id"])
    )
    error = validate_error(response, ApiErrorId.ERR_ACCOUNT_SCOPE_VIOLATION.value)
    assert error["error_id"] != ApiErrorId.ERR_CAMPAIGN_NOT_FOUND.value
