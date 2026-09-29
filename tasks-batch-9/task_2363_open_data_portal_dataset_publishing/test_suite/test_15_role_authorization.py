"""
Role authorisation: which operational capacity may call which endpoint, whose
identity the call must carry, and how the portal separates a missing identity from
a forbidden role, a foreign department and a foreign member.
"""

from test_helpers import (
    ANONYMOUS_HEADERS,
    PORTAL_ADMIN_HEADERS,
    PRIVACY_ASSESSOR_HEADERS,
    PRIVACY_ASSESSOR_USER_ID,
    PRIVACY_DECIDER_USER_ID,
    ROLE_DATA_COORDINATOR,
    assert_credit_buckets,
    assert_credit_conservation,
    assert_dataset_states,
    assert_money,
    assert_priority,
    assert_scorecard_balanced,
    factories,
    fixtures,
    get_success_data,
    make_data_coordinator_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

# A coordinator's identity is the acting department's id, so a request that names
# the role but carries no `X-User-ID` header supplies no identity at all.
COORDINATOR_HEADERS_WITHOUT_IDENTITY = {
    "X-User-Role": ROLE_DATA_COORDINATOR,
    "Content-Type": "application/json",
}

PARKS_DEPARTMENT = {
    "name": "City Parks Department",
    "code": "PARKS",
    "contact_email": "opendata@parks.city.gov",
}

BEN = {"email": "ben@civic.example", "display_name": "Ben Mapper"}

FOREIGN_ISSUE = {
    "severity": "HIGH",
    "category": "ACCURACY",
    "description": "Counts look doubled for two corridors",
}


def test_portal_admin_registers_the_shared_registries_and_grants_credits(api):
    """The programme office alone stands up departments, licences, runners and credits.

    The PRD: "The programme office holds the shared registries (departments,
    licences, ingest runners, credit grants), metadata acceptance, usage-analytics
    ingestion, high-value commitments, showcase moderation, community-request
    adjudication, the operational sweep and the logical clock." Its `X-User-ID` is
    opaque: "When `X-User-Role` is `PortalAdmin`, `X-User-ID` is an opaque operator
    identifier not tied to any persisted entity; the server never compares it to any
    entity's `id`."

    Each of the three registry creates mints a persisted row, and "Endpoints that
    create a new persistent resource respond with HTTP status code 201; every other
    successful request — reads, list queries, computed reads, state transitions,
    updates and operational actions — responds with HTTP status code 200."

    The PRD fixes what those rows look like: "A freshly registered department starts
    with all four credit buckets at 0.00, all four risk counters at zero,
    `risk_points` at 0 and `compliance_posture` at `OPEN`." — "otherwise, if
    attribution is required, commercial use is allowed and share-alike is not
    required, the class is `ATTRIBUTION`" with "A new licence has `retired` false." —
    "The programme office registers an `IngestRunner` with a `name` and an optional
    `cooldown_minutes` between 0 and 120, defaulting to 15, which is the mandatory
    buffer appended after every armed window on that worker so that consecutive jobs
    cannot crowd each other." and "A new runner has `status` `ACTIVE` and
    `armed_window_count` 0."

    The grant then lands entirely in the balance bucket: "Credits arrive only by
    grant: the programme office supplies a `credit_units` amount, strictly greater
    than zero, together with an optional `memo` recording why, and the grant raises
    `credits_issued_units` and `credit_balance_units` by that amount while leaving
    `credits_escrowed_units` and `credits_consumed_units` untouched." The scorecard
    reports the reconciliation: "A departmental scorecard capability exposes the
    posture arithmetic and the credit reconciliation side by side, answering with the
    department's `department_id`, its `compliance_posture`, `risk_points`,
    `breached_dataset_count`, `stale_dataset_count`, `remediation_dataset_count` and
    `overdue_correction_count`, all four credit buckets, and a boolean
    `credit_ledger_balanced` asserting that the conservation invariant of §2.10
    currently holds."

    Design: Corner/rbac/portal_admin_performs_its_exclusive_registry_operations
    """
    fixtures.reset_clock_to_start(api=api)

    department = validate_success(
        api.create_department(factories.department_payload(), PORTAL_ADMIN_HEADERS), 201
    )
    license_term = validate_success(
        api.create_license(factories.license_payload(), PORTAL_ADMIN_HEADERS), 201
    )
    runner = validate_success(
        api.create_ingest_runner(factories.ingest_runner_payload(), PORTAL_ADMIN_HEADERS), 201
    )

    assert department["code"] == "DOT", f"Expected code DOT, got {department['code']}"
    assert department["compliance_posture"] == "OPEN", (
        f"Expected compliance_posture OPEN, got {department['compliance_posture']}"
    )
    assert department["risk_points"] == 0, (
        f"Expected risk_points 0 on a fresh department, got {department['risk_points']}"
    )
    assert_credit_buckets(department, issued=0.00, balance=0.00, escrowed=0.00, consumed=0.00)

    assert license_term["reuse_permission_class"] == "ATTRIBUTION", (
        f"Expected reuse_permission_class ATTRIBUTION, "
        f"got {license_term['reuse_permission_class']}"
    )
    assert license_term["retired"] is False, (
        f"A new licence must have retired false, got {license_term['retired']!r}"
    )

    assert runner["status"] == "ACTIVE", f"Expected runner status ACTIVE, got {runner['status']}"
    assert runner["cooldown_minutes"] == 15, (
        f"Expected cooldown_minutes 15, got {runner['cooldown_minutes']}"
    )
    assert runner["armed_window_count"] == 0, (
        f"Expected armed_window_count 0 on a fresh runner, got {runner['armed_window_count']}"
    )

    get_success_data(
        api.grant_department_credits(
            department["id"],
            factories.credit_grant_payload(credit_units=100.00),
            PORTAL_ADMIN_HEADERS,
        )
    )

    funded = fixtures.read_department(department["id"], api=api)
    assert_credit_buckets(funded, issued=100.00, balance=100.00, escrowed=0.00, consumed=0.00)
    assert_credit_conservation(funded)

    scorecard = validate_success(
        api.get_department_scorecard(department["id"], PORTAL_ADMIN_HEADERS)
    )
    assert scorecard["department_id"] == department["id"], (
        f"Expected department_id {department['id']}, got {scorecard['department_id']}"
    )
    assert_scorecard_balanced(scorecard)


def test_coordinator_cannot_accept_its_own_metadata_record(api):
    """Metadata acceptance belongs to the programme office, not to the drafting department.

    The PRD on the coordinator: "It cannot grant credits, accept its own metadata
    record, decide a privacy clearance, or moderate community content." The decision
    is the reviewer's: "The programme office then decides the submitted record,
    supplying a `decision`."

    The refusal is the generic role check: "Role authorisation, on every endpoint: the
    acting role appears in the endpoint's authorised list — otherwise
    `ERR_ROLE_NOT_PERMITTED` (403)." So the coordinator's acceptance attempt answers
    `ERR_ROLE_NOT_PERMITTED` at 403 and the record must stay exactly where it was,
    while the same call from the programme office lands the transition: "An `ACCEPT`
    decision moves the record `SUBMITTED → ACCEPTED` and is guarded by three
    conditions…"

    Design: Corner/rbac/coordinator_cannot_accept_metadata_returns_403
    """
    ctx = fixtures.setup_screening_dataset(api=api, credit_units=0)
    record = fixtures.draft_metadata_record(
        ctx["dataset_id"], ctx["license_id"], ctx["department_id"], api=api
    )
    submitted = fixtures.submit_metadata_record(record["id"], ctx["department_id"], api=api)
    assert submitted["status"] == "SUBMITTED", (
        f"Setup must leave the record SUBMITTED, got {submitted['status']}"
    )

    validate_error(
        api.decide_metadata_record(
            record["id"], factories.decision_payload("ACCEPT"), ctx["coordinator_headers"]
        ),
        "ERR_ROLE_NOT_PERMITTED",
        403,
    )

    unchanged = validate_success(api.get_metadata_record(record["id"], ANONYMOUS_HEADERS))
    assert unchanged["status"] == "SUBMITTED", (
        f"A refused acceptance must leave the record SUBMITTED, got {unchanged['status']}"
    )
    assert unchanged["version"] == submitted["version"], (
        f"A refused acceptance must not mutate the record: expected version "
        f"{submitted['version']}, got {unchanged['version']}"
    )

    accepted = fixtures.accept_metadata_record(record["id"], api=api)
    assert accepted["status"] == "ACCEPTED", (
        f"The programme office must be able to accept the same record, "
        f"got {accepted['status']}"
    )


def test_portal_admin_cannot_publish_a_departments_dataset(api):
    """Publication stays with the department that stewards the extract.

    The PRD on the programme office: "It cannot author or clear privacy assessments,
    and it cannot inventory or publish a department's datasets." The refusal is the
    generic role check: "Role authorisation, on every endpoint: the acting role
    appears in the endpoint's authorised list — otherwise `ERR_ROLE_NOT_PERMITTED`
    (403)."

    A publication that had gone through would have moved the dataset on: "On the
    dataset, `version_index_high_water` becomes 1, `live_row_count` becomes the
    initial row count, and `last_published_at` becomes the current logical instant."
    So the refused dataset must still show the inventory defaults the PRD gives it:
    "A newly inventoried dataset sits at `publication_status` `INVENTORIED` and
    `currency_status` `CURRENT`, with `public_access_suspended` and
    `high_value_committed` both false, `engagement_index` and `observed_demand_score`
    both 0.00, `usage_epochs` and `showcase_apps` both empty, `live_row_count` and
    `version_index_high_water` and `days_overdue` and `staleness_alert_count` all
    zero, and `last_published_at`, `next_due_at`, `last_staleness_alert_at` and
    `remediation_opened_at` all null." — held at `READY` by the readiness transition,
    which "increments the dataset's `version` and changes nothing else."

    Design: Corner/rbac/portal_admin_cannot_publish_dataset_returns_403
    """
    ctx = fixtures.setup_ready_dataset(api=api, credit_units=0)
    assert_dataset_states(ctx["dataset"], publication_status="READY")

    validate_error(
        api.publish_dataset(
            ctx["dataset_id"],
            factories.publish_payload(initial_row_count=50000),
            PORTAL_ADMIN_HEADERS,
        ),
        "ERR_ROLE_NOT_PERMITTED",
        403,
    )

    unchanged = fixtures.read_dataset(ctx["dataset_id"], api=api)
    assert_dataset_states(unchanged, publication_status="READY")
    assert unchanged["last_published_at"] is None, (
        f"A refused publication must leave last_published_at null, "
        f"got {unchanged['last_published_at']!r}"
    )
    assert unchanged["version_index_high_water"] == 0, (
        f"A refused publication must leave version_index_high_water 0, "
        f"got {unchanged['version_index_high_water']}"
    )
    assert unchanged["live_row_count"] == 0, (
        f"A refused publication must leave live_row_count 0, got {unchanged['live_row_count']}"
    )

    versions, meta = validate_paginated(api.list_dataset_versions(ANONYMOUS_HEADERS))
    assert meta["total_count"] == 0, (
        f"A refused publication must mint no version, got total_count {meta['total_count']}"
    )


def test_coordinator_without_an_identity_header_is_unauthenticated(api):
    """A coordinator that supplies no identity fails authentication, not authorisation.

    The PRD: "When `X-User-Role` is `DataCoordinator`, `X-User-ID` is the `id` of the
    acting `Department`." and "A request whose `X-User-Role` is missing or is not one
    of those five strings, or whose `X-User-ID` is missing for a role that requires an
    identity, is rejected with `ERR_UNAUTHENTICATED` (401)."

    The order is contractual: "All validations are evaluated in the ascending priority
    order below…" and "Priorities 1 through 5 form the generic preamble that every
    applicable request passes through before any domain rule runs." Priority 1 is
    "Authentication, on every endpoint: `X-User-Role` and `X-User-ID` are present and
    the role is one of the five declared names, with `Anonymous` exempt from
    `X-User-ID` — otherwise `ERR_UNAUTHENTICATED` (401)." — ahead of both "Role
    authorisation, on every endpoint: the acting role appears in the endpoint's
    authorised list — otherwise `ERR_ROLE_NOT_PERMITTED` (403)." and "Departmental
    scope, on every `DataCoordinator`-only endpoint:
    `ERR_DEPARTMENT_SCOPE_VIOLATION` (403) as described in §2.1." So the answer is
    `ERR_UNAUTHENTICATED` at 401 and neither of the two 403s, and no dataset is
    inventoried — where "`total_count` is the number of rows matching the filters
    before pagination is applied."

    Design: Corner/rbac/coordinator_call_without_user_id_header_is_unauthorized
    """
    fixtures.reset_clock_to_start(api=api)
    department = fixtures.register_department(api=api)

    error_data = validate_error(
        api.create_dataset(
            factories.dataset_payload(department["id"]), COORDINATOR_HEADERS_WITHOUT_IDENTITY
        ),
        "ERR_UNAUTHENTICATED",
        401,
    )
    forbidden_ids = ("ERR_ROLE_NOT_PERMITTED", "ERR_DEPARTMENT_SCOPE_VIOLATION")
    assert error_data["error_id"] not in forbidden_ids, (
        f"A missing identity must not surface as a role or scope failure, "
        f"got {error_data['error_id']}"
    )

    datasets, meta = validate_paginated(api.list_datasets(ANONYMOUS_HEADERS))
    assert meta["total_count"] == 0, (
        f"An unauthenticated create must inventory nothing, got total_count {meta['total_count']}"
    )
    assert datasets == [], f"Expected an empty catalogue, got {len(datasets)} rows"


def test_assessment_author_cannot_clear_its_own_assessment(api):
    """Two reviewers carry the same role, and only the recorded identity separates them.

    The PRD: "The server stamps `assessor_user_id` with the authoring reviewer's
    `X-User-ID`, leaves `verified_smallest_cell_size` and `decided_by_user_id` null,
    and sets `status` to `DRAFT`." and "Segregation of duties is enforced by comparing
    those two recorded operator identifiers to each other: a reviewer whose
    `X-User-ID` equals the assessment's `assessor_user_id` may not decide that
    assessment, and the attempt is rejected with `ERR_SEGREGATION_OF_DUTIES` (403)."

    The refusal is therefore `ERR_SEGREGATION_OF_DUTIES` at 403 and not a role
    failure — the authoring reviewer holds a role the endpoint authorises — and the
    assessment must keep its `SUBMITTED` standing with `decided_by_user_id` still
    null. A second reviewer then decides the very same row, because "Both outcomes
    stamp `decided_by_user_id` with the deciding reviewer's `X-User-ID`, both require
    that this identifier differ from the recorded `assessor_user_id`, and both
    increment the assessment's `version` — but their conditions and their recorded
    results diverge." and "A `CLEAR` decision moves the assessment `SUBMITTED →
    CLEARED` and additionally requires `clearance_risk_score` to be strictly below
    60.00…"

    Design: Corner/rbac/privacy_clearance_by_the_assessment_author_returns_forbidden
    """
    ctx = fixtures.setup_screening_dataset(api=api, credit_units=0)
    assessment = fixtures.open_privacy_assessment(ctx["dataset_id"], api=api)
    fixtures.revise_privacy_assessment(
        assessment["id"], api=api, verified_smallest_cell_size=20
    )
    submitted = fixtures.submit_privacy_assessment(assessment["id"], api=api)
    assert submitted["assessor_user_id"] == PRIVACY_ASSESSOR_USER_ID, (
        f"Setup must record the authoring reviewer, got {submitted['assessor_user_id']!r}"
    )

    validate_error(
        api.decide_privacy_assessment(
            assessment["id"], factories.decision_payload("CLEAR"), PRIVACY_ASSESSOR_HEADERS
        ),
        "ERR_SEGREGATION_OF_DUTIES",
        403,
    )

    unchanged = validate_success(
        api.get_privacy_assessment(assessment["id"], PORTAL_ADMIN_HEADERS)
    )
    assert unchanged["status"] == "SUBMITTED", (
        f"A refused clearance must leave the assessment SUBMITTED, got {unchanged['status']}"
    )
    assert unchanged["decided_by_user_id"] is None, (
        f"A refused clearance must leave decided_by_user_id null, "
        f"got {unchanged['decided_by_user_id']!r}"
    )
    assert unchanged["assessor_user_id"] == PRIVACY_ASSESSOR_USER_ID, (
        f"Expected assessor_user_id {PRIVACY_ASSESSOR_USER_ID}, "
        f"got {unchanged['assessor_user_id']!r}"
    )

    cleared = fixtures.clear_privacy_assessment(assessment["id"], api=api)
    assert cleared["status"] == "CLEARED", (
        f"A second reviewer must be able to clear the same row, got {cleared['status']}"
    )
    assert cleared["decided_by_user_id"] == PRIVACY_DECIDER_USER_ID, (
        f"Expected decided_by_user_id {PRIVACY_DECIDER_USER_ID}, "
        f"got {cleared['decided_by_user_id']!r}"
    )


def test_coordinator_of_another_department_cannot_screen_the_dataset(api):
    """Two departments are peers, and neither may move the other's inventory.

    The PRD: "Ownership checks on any dataset-scoped write compare the target
    dataset's `department_id` to `X-User-ID`; when a coordinator inventories a new
    dataset, the comparison is against the `department_id` supplied in the request
    body instead. A mismatch is rejected with `ERR_DEPARTMENT_SCOPE_VIOLATION`
    (403)." and, on the ordering, "Departmental scope, on every
    `DataCoordinator`-only endpoint: `ERR_DEPARTMENT_SCOPE_VIOLATION` (403) as
    described in §2.1."

    So the PARKS coordinator — a legitimate holder of the role, so no
    `ERR_ROLE_NOT_PERMITTED` — is refused with `ERR_DEPARTMENT_SCOPE_VIOLATION` on a
    DOT dataset, which must stay untouched at `version` 1, since "`version`
    (integer): a counter that starts at 1 on creation and increments by exactly 1 on
    every mutation of that row, including mutations the server performs on its own
    initiative as a cascade from some other resource's transition." The owning
    coordinator then makes the identical call: "Moving a dataset out of raw inventory
    is the coordinator's declaration that readiness review has started: the dataset
    advances `INVENTORIED → SCREENING`."

    Design: Corner/rbac/coordinator_of_another_department_cannot_screen_dataset
    """
    ctx = fixtures.setup_funded_department(api=api, credit_units=0)
    parks = fixtures.register_department(api=api, **PARKS_DEPARTMENT)
    dataset = fixtures.inventory_dataset(ctx["department_id"], api=api)
    assert_dataset_states(dataset, publication_status="INVENTORIED")

    validate_error(
        api.screen_dataset(dataset["id"], make_data_coordinator_headers(parks["id"])),
        "ERR_DEPARTMENT_SCOPE_VIOLATION",
        403,
    )

    unchanged = fixtures.read_dataset(dataset["id"], api=api)
    assert_dataset_states(unchanged, publication_status="INVENTORIED")
    assert unchanged["version"] == 1, (
        f"A refused screening must leave the dataset at version 1, got {unchanged['version']}"
    )

    screened = fixtures.screen_dataset(dataset["id"], ctx["department_id"], api=api)
    assert_dataset_states(screened, publication_status="SCREENING")


def test_member_cannot_file_a_quality_issue_for_another_member(api):
    """A member may only speak for itself, even when the member it names exists.

    The PRD: "Ownership checks compare `X-User-ID` to whichever member reference the
    body carries — `reporter_member_id` when filing a quality issue,
    `requester_member_id` when asking for a new dataset, `member_id` when casting a
    vote, `submitter_member_id` when submitting a showcase application. A mismatch is
    rejected with `ERR_MEMBER_SCOPE_VIOLATION` (403)." Filing is explicitly
    self-referential: "The member supplies the `dataset_id` the defect was found in,
    their own `reporter_member_id`, a `severity` of `LOW`, `MEDIUM`, `HIGH` or
    `CRITICAL`, a `category` of `ACCURACY`, `COMPLETENESS`, `TIMELINESS`, `SCHEMA` or
    `PRIVACY`, and a free-text `description` of the defect."

    Because both members are registered, the body foreign key resolves and the
    failure is the self-scope check rather than a 404 — "Priorities 1 through 5 form
    the generic preamble that every applicable request passes through before any
    domain rule runs." and priority 7 is "Member self-scope, on `POST
    /open-data/quality-issues`, `POST /open-data/dataset-requests`, `POST
    /open-data/dataset-requests/{requestId}/votes` and `POST
    /open-data/datasets/{datasetId}/showcase-apps`: `ERR_MEMBER_SCOPE_VIOLATION`
    (403) as described in §2.1." So the answer is `ERR_MEMBER_SCOPE_VIOLATION` at 403
    and not `ERR_MEMBER_NOT_FOUND`, no issue is filed, and neither member is credited
    or penalised: "A new member begins with `accepted_issue_count`,
    `rejected_issue_count`, `approved_showcase_count` and `decay_epochs` all zero,
    `reputation_score` 50.00, `vote_weight` 2, `status` `ACTIVE`, and
    `last_credited_at` initialised to the member's own `created_at`."

    Design: Corner/rbac/member_filing_for_another_member_returns_forbidden
    """
    ctx = fixtures.setup_published_dataset(api=api, credit_units=0)
    ana = fixtures.setup_member(api=api)
    ben = fixtures.setup_member(api=api, **BEN)

    error_data = validate_error(
        api.create_quality_issue(
            factories.quality_issue_payload(ctx["dataset_id"], ana["member_id"], **FOREIGN_ISSUE),
            ben["member_headers"],
        ),
        "ERR_MEMBER_SCOPE_VIOLATION",
        403,
    )
    assert error_data["error_id"] != "ERR_MEMBER_NOT_FOUND", (
        f"Both member rows exist, so the failure must not be a resolution failure, "
        f"got {error_data['error_id']}"
    )

    issues, meta = validate_paginated(api.list_quality_issues(ANONYMOUS_HEADERS))
    assert meta["total_count"] == 0, (
        f"A refused filing must create no issue, got total_count {meta['total_count']}"
    )
    assert issues == [], f"Expected no quality issues, got {len(issues)} rows"

    for label, member_id in (("Ana", ana["member_id"]), ("Ben", ben["member_id"])):
        member = fixtures.read_member(member_id, api=api)
        assert_money(member["reputation_score"], 50.00, f"{label} reputation_score")
        assert member["accepted_issue_count"] == 0, (
            f"Expected {label} accepted_issue_count 0, got {member['accepted_issue_count']}"
        )
        assert member["rejected_issue_count"] == 0, (
            f"Expected {label} rejected_issue_count 0, got {member['rejected_issue_count']}"
        )
        assert member["status"] == "ACTIVE", (
            f"Expected {label} status ACTIVE, got {member['status']}"
        )


def test_anonymous_browses_the_published_catalogue_and_registers_as_a_member(api):
    """The public surface needs no identity: catalogue, analytics, history, registration.

    The PRD: "When `X-User-Role` is `Anonymous`, there is no `X-User-ID` at all and
    nothing is compared to any entity's `id`. Anonymous callers may browse the public
    catalogue and register themselves as a community member; they hold no other write
    authority." The endpoint table's authorisation column is the contract for who may
    call what: "The `Authorized Role(s)` column names the roles permitted to call each
    endpoint; a value of `Any` means all five roles, including `Anonymous`, may call
    it."

    Pagination defaults are fixed — "`limit` caps the number of rows returned; when it
    is omitted it defaults to 10, its minimum accepted value is 1 and its maximum
    accepted value is 100." and "`offset` is the number of rows to skip; when omitted
    it defaults to 0 and its minimum accepted value is 0." — and "Every list response
    carries `limit`, `offset`, `total_count` and `has_more` in the `meta` object of
    the envelope, where `total_count` is the number of rows matching the filters
    before pagination is applied."

    Publication set what the reads must show: "On the dataset,
    `version_index_high_water` becomes 1, `live_row_count` becomes the initial row
    count, and `last_published_at` becomes the current logical instant." and "A first
    `DatasetVersion` is minted with `version_index` set to the dataset's
    `version_index_high_water` plus one — which is 1 — a `version_label` of `"v"`
    followed by that index, a `change_type` of `INITIAL`, a `row_count` equal to the
    supplied `initial_row_count`, a `status` of `LIVE`, a `published_at` stamped at
    the current logical instant, and `supersedes_version_id` null because there is
    nothing before it."

    The analytics read is scored on the observed variant — "Once the dataset's
    `publication_status` is `PUBLISHED` or `UNDER_REMEDIATION`, the demand term
    becomes the measured `observed_demand_score` and the variant is `AS_OBSERVED`."
    with "A dataset whose `usage_epochs` is empty has an `engagement_index` of 0.00."
    — so with "The first is a demand term weighted at 0.45.", "The second is
    `policy_value_score` weighted at 0.35." and no community pressure, "The three
    weighted terms are then added together and the finished sum is rounded half up to
    two decimal places exactly once, never term by term, giving `priority_score`."
    leaves 0.35 × 96 = 33.60.

    Registration answers 201 with the member defaults: "A new member begins with
    `accepted_issue_count`, `rejected_issue_count`, `approved_showcase_count` and
    `decay_epochs` all zero, `reputation_score` 50.00, `vote_weight` 2, `status`
    `ACTIVE`, and `last_credited_at` initialised to the member's own `created_at`."

    Design: Corner/rbac/anonymous_browses_the_public_catalogue
    """
    ctx = fixtures.setup_published_dataset(api=api, credit_units=0, initial_row_count=50000)
    assert "X-User-ID" not in ANONYMOUS_HEADERS, (
        f"The anonymous caller must send no identity, got {sorted(ANONYMOUS_HEADERS)}"
    )

    catalogue, meta = validate_paginated(api.list_datasets(ANONYMOUS_HEADERS))
    assert meta["total_count"] == 1, f"Expected total_count 1, got {meta['total_count']}"
    assert meta["has_more"] is False, f"Expected has_more false, got {meta['has_more']!r}"
    assert meta["limit"] == 10, f"Expected the default limit 10, got {meta['limit']}"
    assert meta["offset"] == 0, f"Expected the default offset 0, got {meta['offset']}"
    assert len(catalogue) == 1, f"Expected one catalogue row, got {len(catalogue)}"

    dataset = validate_success(api.get_dataset(ctx["dataset_id"], ANONYMOUS_HEADERS))
    assert_dataset_states(dataset, publication_status="PUBLISHED")
    assert dataset["live_row_count"] == 50000, (
        f"Expected live_row_count 50000, got {dataset['live_row_count']}"
    )

    analytics = validate_success(
        api.get_dataset_analytics(ctx["dataset_id"], ANONYMOUS_HEADERS)
    )
    assert analytics["dataset_id"] == ctx["dataset_id"], (
        f"Expected dataset_id {ctx['dataset_id']}, got {analytics['dataset_id']}"
    )
    assert_money(analytics["engagement_index"], 0.00, "engagement_index")
    assert_priority(analytics, priority_score=33.60, priority_score_variant="AS_OBSERVED")

    versions, version_meta = validate_paginated(api.list_dataset_versions(ANONYMOUS_HEADERS))
    assert version_meta["total_count"] == 1, (
        f"Expected one published version, got total_count {version_meta['total_count']}"
    )
    first_version = versions[0]
    assert first_version["version_label"] == "v1", (
        f"Expected version_label v1, got {first_version['version_label']}"
    )
    assert first_version["change_type"] == "INITIAL", (
        f"Expected change_type INITIAL, got {first_version['change_type']}"
    )
    assert first_version["status"] == "LIVE", (
        f"Expected the first version LIVE, got {first_version['status']}"
    )

    member = validate_success(
        api.register_member(factories.member_payload(), ANONYMOUS_HEADERS), 201
    )
    assert_money(member["reputation_score"], 50.00, "reputation_score")
    assert member["vote_weight"] == 2, f"Expected vote_weight 2, got {member['vote_weight']}"
    assert member["status"] == "ACTIVE", f"Expected status ACTIVE, got {member['status']}"


def test_anonymous_cannot_read_the_department_scorecard(api):
    """The public surface stops at the catalogue: compliance arithmetic is not public.

    The PRD's endpoint table restricts the scorecard read — "Computed read: posture
    arithmetic and the credit-conservation reconciliation for one department |
    `DataCoordinator`, `PortalAdmin`" — and "The `Authorized Role(s)` column names the
    roles permitted to call each endpoint; a value of `Any` means all five roles,
    including `Anonymous`, may call it." An anonymous caller is authenticated, since
    "`Anonymous` is the sole exception: it requires no `X-User-ID`.", so the failure is
    the role check: "A syntactically valid caller whose role is not listed among an
    endpoint's authorised roles is rejected with `ERR_ROLE_NOT_PERMITTED` (403)."

    The department row itself stays public, and the permitted caller still sees the
    reconciliation: "A departmental scorecard capability exposes the posture
    arithmetic and the credit reconciliation side by side, answering with the
    department's `department_id`, its `compliance_posture`, `risk_points`,
    `breached_dataset_count`, `stale_dataset_count`, `remediation_dataset_count` and
    `overdue_correction_count`, all four credit buckets, and a boolean
    `credit_ledger_balanced` asserting that the conservation invariant of §2.10
    currently holds."

    Design: Corner/rbac/anonymous_cannot_read_department_scorecard_returns_403
    """
    ctx = fixtures.setup_funded_department(api=api, credit_units=100.00)

    validate_error(
        api.get_department_scorecard(ctx["department_id"], ANONYMOUS_HEADERS),
        "ERR_ROLE_NOT_PERMITTED",
        403,
    )

    department = validate_success(api.get_department(ctx["department_id"], ANONYMOUS_HEADERS))
    assert department["id"] == ctx["department_id"], (
        f"The department row must stay readable by anyone: expected id "
        f"{ctx['department_id']}, got {department['id']}"
    )

    scorecard = validate_success(
        api.get_department_scorecard(ctx["department_id"], PORTAL_ADMIN_HEADERS)
    )
    assert_credit_buckets(scorecard, issued=100.00, balance=100.00, escrowed=0.00, consumed=0.00)
    assert_scorecard_balanced(scorecard)
