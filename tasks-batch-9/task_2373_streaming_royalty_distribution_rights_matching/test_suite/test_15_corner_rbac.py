"""Role authorization corners: exclusive versus shared operations, rights-holder
peer isolation, and the two segregation-of-duties couples."""

from datetime import datetime

from test_helpers import (
    ADMIN_SETTLE_USER_ID,
    ANALYST_FUZZY_MATCHER_USER_ID,
    ANALYST_REVIEWER_USER_ID,
    CANONICAL_SCHEDULE,
    TEST_DEFAULTS,
    TEST_USERS,
    ApiErrorId,
    append_line,
    audit_engagement_payload,
    calculate_pool,
    create_batch,
    create_effective_schedule,
    create_engagement,
    create_label,
    create_period,
    create_pool,
    create_publisher,
    create_recording,
    create_statement,
    file_and_approve_registration,
    file_registration_under_review,
    finalize_pool,
    findings_payload,
    issue_statement,
    make_rights_holder_user_headers,
    make_rights_ops_analyst_headers,
    make_royalty_admin_headers,
    produce_audit_data,
    record_findings,
    rights_registration_payload,
    seal_and_match_batch,
    set_clock,
    settlement_payload,
    statement_lines,
    statement_payload,
    usage_batch_payload,
    validate_error,
    validate_success,
    work_version,
)

ADMIN_HEADERS = TEST_USERS["royalty_admin_headers"]
ANALYST_HEADERS = TEST_USERS["rights_ops_analyst_headers"]
REGULATOR_HEADERS = TEST_USERS["regulatory_officer_headers"]
MATCHER_HEADERS = TEST_USERS["fuzzy_matcher_headers"]
REVIEWER_HEADERS = TEST_USERS["reviewer_headers"]

# Ids that intentionally match no row: role authorization is answered before any
# referenced identifier is resolved.
ABSENT_POOL_ID = "11111111-1111-4111-8111-111111111130"
ABSENT_HOLDER_ID = "11111111-1111-4111-8111-111111111132"
ABSENT_STATEMENT_ID = "11111111-1111-4111-8111-111111111133"
ABSENT_ENGAGEMENT_ID = "11111111-1111-4111-8111-111111111134"
ABSENT_STATEMENT_HOLDER_ID = "11111111-1111-4111-8111-111111111135"
ABSENT_PERIOD_ID = "11111111-1111-4111-8111-111111111136"
ABSENT_REGISTRATION_ID = "11111111-1111-4111-8111-111111111137"
ABSENT_RATE_SCHEDULE_ID = "11111111-1111-4111-8111-111111111138"
UNKNOWN_HOLDER_USER_ID = "11111111-1111-4111-8111-111111111139"
ABSENT_USAGE_BATCH_ID = "11111111-1111-4111-8111-111111111140"

UNKNOWN_HOLDER_USER_HEADERS = make_rights_holder_user_headers(UNKNOWN_HOLDER_USER_ID)

INTAKE_ANALYST_USER_ID = "analyst-intake-3"

SINGLE_LINE_STATEMENT_NET_PAYABLE_CENTS = 689999
ASSERTED_UNDERPAYMENT_CENTS = 5000
SETTLED_AMOUNT_CENTS = 5000


def _assert_instant_equals(actual: str, expected: str, label: str) -> None:
    """Compare two ISO 8601 UTC instants regardless of fractional-digit spelling."""
    parsed_actual = datetime.fromisoformat(actual.replace("Z", "+00:00"))
    parsed_expected = datetime.fromisoformat(expected.replace("Z", "+00:00"))
    assert parsed_actual == parsed_expected, (
        f"{label}: expected instant {expected}, got {actual}"
    )


def _setup_single_line_issued_statement(api):
    """A label plus an unrelated publisher, an EFFECTIVE GB/INDIVIDUAL schedule, a
    single 450000-play line matched by exact ISRC, the label's MASTER WORLD claim
    approved, the pool finalized and the label's one-line statement ISSUED."""
    label = create_label(api)
    publisher = create_publisher(api, legal_name="Tidewater Songs", rate_bps=1000)
    create_effective_schedule(api, **dict(CANONICAL_SCHEDULE))

    period = create_period(api)
    recording = create_recording(api)

    batch = create_batch(api, period["id"])
    append_line(
        api,
        batch["id"],
        reported_isrc=TEST_DEFAULTS["RECORDING_A_ISRC"],
        reported_title=TEST_DEFAULTS["RECORDING_A_TITLE"],
        territory_code="GB",
        subscription_tier="INDIVIDUAL",
        play_count=450000,
    )
    seal_and_match_batch(api, batch["id"])

    file_and_approve_registration(
        api,
        recording["id"],
        label["id"],
        right_type="MASTER",
        routing="DIRECT",
        share_bps=10000,
        territory_set=["WORLD"],
    )

    pool = create_pool(
        api,
        period["id"],
        territory_code="GB",
        subscription_tier="INDIVIDUAL",
        subscriber_count=1000,
        gross_revenue_cents=1428570,
    )
    calculate_pool(api, pool["id"])
    finalize_pool(api, pool["id"])

    statement = create_statement(api, label["id"], period["id"])
    issued = issue_statement(api, statement["id"])
    lines = statement_lines(api, statement["id"])
    assert len(lines) == 1, "the fixture statement carries exactly one line"

    return {
        "label": label,
        "publisher": publisher,
        "period": period,
        "recording": recording,
        "pool": pool,
        "statement": issued,
        "statement_line": lines[0],
    }


def _setup_asserted_finding(api):
    """The single-line issued statement, its only line produced to the auditing
    holder, and a 5000-cent underpayment asserted by that holder."""
    fixture = _setup_single_line_issued_statement(api)
    engagement = create_engagement(
        api, fixture["label"]["id"], fixture["statement"]["id"]
    )
    produced = produce_audit_data(
        api, engagement["id"], [fixture["statement_line"]["id"]]
    )
    assert produced["production_status"] == "COMPLETE"
    fixture["engagement"] = record_findings(
        api,
        engagement["id"],
        fixture["label"]["id"],
        ASSERTED_UNDERPAYMENT_CENTS,
        finding_note="territory split understated",
    )
    return fixture


def _setup_fuzzy_matched_claim_under_review(api):
    """A recording matched from title and artist alone — no reported ISRC — by the
    matching analyst, and a MASTER GB claim over it sitting in UNDER_REVIEW."""
    label = create_label(api)
    period = create_period(api)
    recording = create_recording(api)

    batch = create_batch(api, period["id"])
    line = append_line(
        api,
        batch["id"],
        reported_title=TEST_DEFAULTS["RECORDING_A_TITLE"],
        reported_artist=TEST_DEFAULTS["RECORDING_A_ARTIST"],
        territory_code="GB",
        subscription_tier="INDIVIDUAL",
        play_count=450000,
    )
    seal_and_match_batch(api, batch["id"], headers=MATCHER_HEADERS)

    registration = file_registration_under_review(
        api,
        recording["id"],
        label["id"],
        right_type="MASTER",
        routing="DIRECT",
        share_bps=10000,
        territory_set=["GB"],
    )
    return {
        "label": label,
        "recording": recording,
        "usage_line": line,
        "registration": registration,
    }


# ─────────────────────────────────────────────────────
# Operations reserved to a single role
# ─────────────────────────────────────────────────────

class TestOperationsReservedToOneRole:
    def test_analyst_may_not_calculate_a_pool(self, api):
        """A RightsOpsAnalyst asking for a pool calculation is refused on role grounds before the pool identifier is resolved.

        PRD: "A well-formed request whose role is not listed among the authorized roles of the target endpoint is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."

        Design: Corner/rbac/every_role_is_refused_the_other_roles_exclusive_operations
        """
        validate_error(
            api.calculate_pool(ABSENT_POOL_ID, ANALYST_HEADERS),
            ApiErrorId.ERR_FORBIDDEN_ROLE.value,
            403,
        )

    def test_admin_may_not_open_an_audit_engagement(self, api):
        """A RoyaltyAdmin trying to exercise an audit right on a holder's behalf is refused on role grounds.

        PRD: "A well-formed request whose role is not listed among the authorized roles of the target endpoint is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."

        Design: Corner/rbac/every_role_is_refused_the_other_roles_exclusive_operations
        """
        validate_error(
            api.create_audit_engagement(
                audit_engagement_payload(ABSENT_HOLDER_ID, ABSENT_STATEMENT_ID),
                ADMIN_HEADERS,
            ),
            ApiErrorId.ERR_FORBIDDEN_ROLE.value,
            403,
        )

    def test_analyst_may_not_record_audit_findings(self, api):
        """A RightsOpsAnalyst asserting an underpayment on an engagement is refused on role grounds.

        PRD: "A well-formed request whose role is not listed among the authorized roles of the target endpoint is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."

        Design: Corner/rbac/every_role_is_refused_the_other_roles_exclusive_operations
        """
        validate_error(
            api.record_audit_findings(
                ABSENT_ENGAGEMENT_ID,
                findings_payload(ASSERTED_UNDERPAYMENT_CENTS),
                ANALYST_HEADERS,
            ),
            ApiErrorId.ERR_FORBIDDEN_ROLE.value,
            403,
        )

    def test_regulatory_officer_may_not_build_a_statement(self, api):
        """A RegulatoryOfficer building a statement is refused on role grounds before the body is even inspected for shape.

        PRD: "A well-formed request whose role is not listed among the authorized roles of the target endpoint is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."

        Design: Corner/rbac/every_role_is_refused_the_other_roles_exclusive_operations
        """
        validate_error(
            api.create_statement(
                statement_payload(ABSENT_STATEMENT_HOLDER_ID, ABSENT_PERIOD_ID, 1),
                REGULATOR_HEADERS,
            ),
            ApiErrorId.ERR_FORBIDDEN_ROLE.value,
            403,
        )

    def test_regulatory_officer_may_not_approve_a_claim(self, api):
        """A RegulatoryOfficer approving an ownership claim is refused on role grounds.

        PRD: "A well-formed request whose role is not listed among the authorized roles of the target endpoint is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."

        Design: Corner/rbac/every_role_is_refused_the_other_roles_exclusive_operations
        """
        validate_error(
            api.approve_rights_registration(
                ABSENT_REGISTRATION_ID, REGULATOR_HEADERS
            ),
            ApiErrorId.ERR_FORBIDDEN_ROLE.value,
            403,
        )

    def test_holder_user_may_not_promulgate_a_rate_schedule(self, api):
        """A RightsHolderUser bringing a rate schedule into force is refused on role grounds.

        PRD: "A well-formed request whose role is not listed among the authorized roles of the target endpoint is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."

        Design: Corner/rbac/every_role_is_refused_the_other_roles_exclusive_operations
        """
        validate_error(
            api.promulgate_rate_schedule(
                ABSENT_RATE_SCHEDULE_ID, UNKNOWN_HOLDER_USER_HEADERS
            ),
            ApiErrorId.ERR_FORBIDDEN_ROLE.value,
            403,
        )

    def test_holder_user_may_not_seal_a_usage_batch(self, api):
        """A RightsHolderUser sealing a usage batch is refused on role grounds.

        PRD: "A well-formed request whose role is not listed among the authorized roles of the target endpoint is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."

        Design: Corner/rbac/every_role_is_refused_the_other_roles_exclusive_operations
        """
        validate_error(
            api.seal_usage_batch(ABSENT_USAGE_BATCH_ID, UNKNOWN_HOLDER_USER_HEADERS),
            ApiErrorId.ERR_FORBIDDEN_ROLE.value,
            403,
        )


# ─────────────────────────────────────────────────────
# Operations shared between roles
# ─────────────────────────────────────────────────────

def test_usage_batches_are_openable_by_both_the_admin_and_the_analyst(api):
    """Both the RoyaltyAdmin and the RightsOpsAnalyst may open a usage batch inside an open period.

    PRD: "Inside an `OPEN` period, a `RightsOpsAnalyst` or a `RoyaltyAdmin` opens a **usage batch** — one reporting source's submission — by naming the owning period through `period_id` and giving the source a `source_label` of at most 120 characters."

    Design: Corner/rbac/shared_operations_succeed_for_every_permitted_role
    """
    period = create_period(api)

    by_admin = validate_success(
        api.create_usage_batch(
            usage_batch_payload(period["id"], source_label="Admin-loaded feed"),
            ADMIN_HEADERS,
        ),
        201,
    )
    by_analyst = validate_success(
        api.create_usage_batch(
            usage_batch_payload(period["id"], source_label="Analyst-loaded feed"),
            ANALYST_HEADERS,
        ),
        201,
    )
    assert by_admin["id"] != by_analyst["id"]

    batches = validate_success(
        api.list_usage_batches(ADMIN_HEADERS, params={"period_id": period["id"]}), 200
    )
    assert len(batches) == 2


def test_analyst_may_file_a_claim_on_a_holders_behalf(api):
    """A RightsOpsAnalyst may file an ownership claim naming another holder as claimant, because the ownership rule binds only the entity-backed role.

    PRD: "Either a `RightsHolderUser` acting for itself or a `RightsOpsAnalyst` acting on a holder's behalf files one, naming the `work_id` whose rights are claimed, the `claimant_id` asserting the share, the `right_type` being claimed — `MASTER`, `MECHANICAL` or `PERFORMANCE` — the `routing`, which is `DIRECT` when the money goes straight to the claimant and `COLLECTIVE` when it flows through a society, the `share_bps` claimed, between 1 and 10,000, the `territory_set`, the `effective_from` and `effective_to` bounding the ownership interval, and the `expected_work_version` described in §2.8."

    Design: Corner/rbac/shared_operations_succeed_for_every_permitted_role
    """
    label = create_label(api)
    recording = create_recording(
        api,
        identifier=TEST_DEFAULTS["RECORDING_B_ISRC"],
        title="Second Signal",
        artist=TEST_DEFAULTS["RECORDING_A_ARTIST"],
    )

    payload = rights_registration_payload(
        recording["id"],
        label["id"],
        work_version(api, recording["id"]),
        territory_set=["GB"],
    )
    registration = validate_success(
        api.create_rights_registration(
            payload, make_rights_ops_analyst_headers(INTAKE_ANALYST_USER_ID)
        ),
        201,
    )

    assert registration["claimant_id"] == label["id"]
    assert registration["payee_holder_id"] == label["id"]
    assert registration["status"] == "SUBMITTED"


def test_clock_is_settable_by_the_regulatory_officer_and_by_a_holder_user(api):
    """Every role may move the logical clock, and the last instant set is the one later records are stamped with.

    PRD: "Any of the four roles may move the clock to an arbitrary instant by supplying `to_iso8601` to `POST /royalties/_clock/set_current_utc`."

    Design: Corner/rbac/shared_operations_succeed_for_every_permitted_role
    """
    label = create_label(api)

    validate_success(
        set_clock(api, "2026-08-02T00:00:00Z", headers=REGULATOR_HEADERS), 200
    )
    validate_success(
        set_clock(
            api,
            "2026-08-03T00:00:00Z",
            headers=make_rights_holder_user_headers(label["id"]),
        ),
        200,
    )

    period = create_period(api)
    _assert_instant_equals(period["created_at"], "2026-08-03T00:00:00Z", "created_at")


def test_read_endpoints_answer_for_every_authorized_role(api):
    """A resource read declared open to any role answers the admin, the analyst, the regulatory officer and a rights-holder user alike.

    PRD: "In the table below, "Any" means all four roles declared in §2.1 are authorized."

    Design: Corner/rbac/shared_operations_succeed_for_every_permitted_role
    """
    label = create_label(api)
    recording = create_recording(api)
    file_registration_under_review(
        api,
        recording["id"],
        label["id"],
        right_type="MASTER",
        routing="DIRECT",
        share_bps=10000,
        territory_set=["GB"],
    )
    holder_headers = make_rights_holder_user_headers(label["id"])
    every_role = (ADMIN_HEADERS, ANALYST_HEADERS, REGULATOR_HEADERS, holder_headers)

    for headers in every_role:
        seen = validate_success(api.get_work(recording["id"], headers), 200)
        assert seen["identifier"] == TEST_DEFAULTS["RECORDING_A_ISRC"]

    for headers in every_role:
        holder = validate_success(api.get_rights_holder(label["id"], headers), 200)
        assert holder["legal_name"] == "Northbeam Records"

    own_claims = validate_success(
        api.list_rights_registrations(
            holder_headers, params={"claimant_id": label["id"]}
        ),
        200,
    )
    assert len(own_claims) == 1


# ─────────────────────────────────────────────────────
# Peer isolation between rights holders
# ─────────────────────────────────────────────────────

def test_outsider_may_not_read_another_holders_statement(api):
    """A rights-holder user may read only the statement addressed to itself, while the addressed holder reads it successfully.

    PRD: "Concretely, a `RightsHolderUser` may only act on an `AuditEngagement` whose `rights_holder_id` equals `X-User-ID`, may only read a `RoyaltyStatement` whose `rights_holder_id` equals `X-User-ID`, may only file a `RightsRegistration` whose `claimant_id` equals `X-User-ID`, may only supply evidence on a registration whose `claimant_id` equals `X-User-ID`, and may only raise a dispute whose `disputing_holder_id` equals `X-User-ID`."

    Design: Corner/rbac/holder_user_cannot_read_or_audit_another_holders_resources
    """
    fixture = _setup_single_line_issued_statement(api)
    statement_id = fixture["statement"]["id"]

    validate_error(
        api.get_statement(
            statement_id, make_rights_holder_user_headers(fixture["publisher"]["id"])
        ),
        ApiErrorId.ERR_NOT_RESOURCE_OWNER.value,
        403,
    )

    own = validate_success(
        api.get_statement(
            statement_id, make_rights_holder_user_headers(fixture["label"]["id"])
        ),
        200,
    )
    assert own["status"] == "ISSUED"
    assert own["net_payable_cents"] == SINGLE_LINE_STATEMENT_NET_PAYABLE_CENTS


def test_outsider_may_not_open_an_engagement_in_another_holders_name(api):
    """A rights-holder user may open an audit engagement only in its own name, while the named holder's identical request succeeds.

    PRD: "Concretely, a `RightsHolderUser` may only act on an `AuditEngagement` whose `rights_holder_id` equals `X-User-ID`, may only read a `RoyaltyStatement` whose `rights_holder_id` equals `X-User-ID`, may only file a `RightsRegistration` whose `claimant_id` equals `X-User-ID`, may only supply evidence on a registration whose `claimant_id` equals `X-User-ID`, and may only raise a dispute whose `disputing_holder_id` equals `X-User-ID`."

    Design: Corner/rbac/holder_user_cannot_read_or_audit_another_holders_resources
    """
    fixture = _setup_single_line_issued_statement(api)
    payload = audit_engagement_payload(
        fixture["label"]["id"], fixture["statement"]["id"]
    )

    validate_error(
        api.create_audit_engagement(
            payload, make_rights_holder_user_headers(fixture["publisher"]["id"])
        ),
        ApiErrorId.ERR_NOT_RESOURCE_OWNER.value,
        403,
    )

    engagement = validate_success(
        api.create_audit_engagement(
            payload, make_rights_holder_user_headers(fixture["label"]["id"])
        ),
        201,
    )
    assert engagement["required_line_count"] == 1


def test_outsider_may_not_file_a_claim_in_another_holders_name(api):
    """A rights-holder user filing an ownership claim whose claimant is a different holder is refused on ownership grounds.

    PRD: "Violations of any of these are rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."

    Design: Corner/rbac/holder_user_cannot_read_or_audit_another_holders_resources
    """
    fixture = _setup_single_line_issued_statement(api)
    work_id = fixture["recording"]["id"]

    payload = rights_registration_payload(
        work_id,
        fixture["label"]["id"],
        work_version(api, work_id),
        territory_set=["GB"],
    )
    validate_error(
        api.create_rights_registration(
            payload, make_rights_holder_user_headers(fixture["publisher"]["id"])
        ),
        ApiErrorId.ERR_NOT_RESOURCE_OWNER.value,
        403,
    )


# ─────────────────────────────────────────────────────
# Segregation of duties
# ─────────────────────────────────────────────────────

def test_below_certainty_match_stamps_the_matching_analyst_on_the_work(api):
    """A line accepted on title-and-artist agreement alone stamps the winning work with the matching analyst's user id.

    PRD: "When the score is at least 7,500, the line takes `work_id` from the winner and moves to `match_status` `AUTO_MATCHED`; and when that accepted score is strictly below 10,000 — that is, when the service accepted a metadata inference rather than an identifier hit — the winning work's `provisional_match_by_user_id` is stamped with the `X-User-ID` of the calling analyst."

    Design: Corner/rbac/fuzzy_matcher_may_not_approve_the_claim_it_enables
    """
    fixture = _setup_fuzzy_matched_claim_under_review(api)

    line = validate_success(
        api.get_usage_line(fixture["usage_line"]["id"], ANALYST_HEADERS), 200
    )
    assert line["match_confidence_bps"] == 7500
    assert line["match_status"] == "AUTO_MATCHED"

    work = validate_success(
        api.get_work(fixture["recording"]["id"], ANALYST_HEADERS), 200
    )
    assert work["provisional_match_by_user_id"] == ANALYST_FUZZY_MATCHER_USER_ID


def test_matching_analyst_may_not_approve_the_claim_it_enabled(api):
    """The analyst whose below-certainty match attached usage to a work may not approve a claim over that work, and the refused claim keeps its state.

    PRD: "The approving `X-User-ID` must differ from the work's `provisional_match_by_user_id`, so that the analyst who guessed the match cannot be the analyst who monetises it — a violation is `ERR_SEGREGATION_OF_DUTIES`."

    Design: Corner/rbac/fuzzy_matcher_may_not_approve_the_claim_it_enables
    """
    fixture = _setup_fuzzy_matched_claim_under_review(api)
    registration_id = fixture["registration"]["id"]

    validate_error(
        api.approve_rights_registration(registration_id, MATCHER_HEADERS),
        ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value,
        403,
    )

    unchanged = validate_success(
        api.get_rights_registration(registration_id, ANALYST_HEADERS), 200
    )
    assert unchanged["status"] == "UNDER_REVIEW"
    assert unchanged["reviewed_by_user_id"] is None


def test_a_second_analyst_may_approve_the_same_claim(api):
    """The identical approval by an analyst other than the one who matched the usage succeeds, so the rule delays the approval rather than forbidding it.

    PRD: "The approving `X-User-ID` must differ from the work's `provisional_match_by_user_id`, so that the analyst who guessed the match cannot be the analyst who monetises it — a violation is `ERR_SEGREGATION_OF_DUTIES`."

    Design: Corner/rbac/fuzzy_matcher_may_not_approve_the_claim_it_enables
    """
    fixture = _setup_fuzzy_matched_claim_under_review(api)
    registration_id = fixture["registration"]["id"]

    validate_error(
        api.approve_rights_registration(registration_id, MATCHER_HEADERS),
        ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value,
        403,
    )

    approved = validate_success(
        api.approve_rights_registration(registration_id, REVIEWER_HEADERS), 200
    )
    assert approved["status"] == "APPROVED"
    assert approved["reviewed_by_user_id"] == ANALYST_REVIEWER_USER_ID

    work = validate_success(
        api.get_work(fixture["recording"]["id"], ANALYST_HEADERS), 200
    )
    assert work["rights_state"] == "REGISTERED"


def test_finding_recorder_may_not_settle_the_same_engagement(api):
    """Settling an engagement with the same X-User-ID that recorded its finding is refused even when the caller holds RoyaltyAdmin, and the engagement keeps its asserted state.

    PRD: "The settling operator's `X-User-ID` must differ from the engagement's `findings_recorded_by_user_id`, or the request is refused with `ERR_SEGREGATION_OF_DUTIES`."

    Design: Corner/rbac/finding_recorder_may_not_settle_the_same_engagement
    """
    fixture = _setup_asserted_finding(api)
    engagement = fixture["engagement"]
    label_id = fixture["label"]["id"]

    assert engagement["finding_status"] == "ASSERTED"
    assert engagement["findings_recorded_by_user_id"] == label_id

    validate_error(
        api.settle_audit_engagement(
            engagement["id"],
            settlement_payload("UPHOLD", settled_amount_cents=SETTLED_AMOUNT_CENTS),
            make_royalty_admin_headers(label_id),
        ),
        ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value,
        403,
    )

    unchanged = validate_success(
        api.get_audit_engagement(engagement["id"], ADMIN_HEADERS), 200
    )
    assert unchanged["finding_status"] == "ASSERTED"
    assert unchanged["settled_amount_cents"] == 0


def test_a_second_admin_settles_and_the_balance_rises_by_amount_plus_interest(api):
    """A settling operator other than the one who recorded the finding upholds it, and the audited holder's receivable balance rises by the settled amount plus the zero interest earned on an unmoved clock.

    PRD: "The amount is stored, interest is computed, `finding_status` moves `ASSERTED → SETTLED`, and the audited holder's `receivable_balance_cents` rises by exactly `settled_amount_cents` plus `interest_cents`."

    Design: Corner/rbac/finding_recorder_may_not_settle_the_same_engagement
    """
    fixture = _setup_asserted_finding(api)
    label_id = fixture["label"]["id"]

    settled = validate_success(
        api.settle_audit_engagement(
            fixture["engagement"]["id"],
            settlement_payload("UPHOLD", settled_amount_cents=SETTLED_AMOUNT_CENTS),
            make_royalty_admin_headers(ADMIN_SETTLE_USER_ID),
        ),
        200,
    )
    assert settled["finding_status"] == "SETTLED"
    assert settled["settled_amount_cents"] == SETTLED_AMOUNT_CENTS
    assert settled["interest_cents"] == 0
    assert settled["production_status"] == "COMPLETE"

    holder = validate_success(api.get_rights_holder(label_id, ADMIN_HEADERS), 200)
    assert holder["receivable_balance_cents"] == (
        SINGLE_LINE_STATEMENT_NET_PAYABLE_CENTS + SETTLED_AMOUNT_CENTS
    )
