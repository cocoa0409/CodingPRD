"""
Catalogue records as the API hands them back: the initial state of a freshly
inventoried dataset, the reuse class derived from a licence's permission flags,
the system-minted identity of a community member, the request-shape and
resolution failures guarding those creates, and the cross-aggregate transfer of
community pressure onto a published dataset.
"""

from test_helpers import (
    ANONYMOUS_HEADERS,
    ERR_DATASET_NOT_FOUND,
    ERR_DEPARTMENT_NOT_FOUND,
    ERR_INVALID_REQUEST,
    NON_EXISTENT_UUID,
    PORTAL_ADMIN_HEADERS,
    assert_common_fields,
    assert_dataset_states,
    assert_envelope_object,
    assert_money,
    assert_priority,
    factories,
    fixtures,
    make_data_coordinator_headers,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_inventoried_dataset_returns_initial_states_and_as_declared_priority_of_75(api):
    """Creating a dataset answers with the whole row: both state dimensions at their
    initial values and the declared priority already computed.

    The PRD: "A newly inventoried dataset sits at `publication_status` `INVENTORIED` and
    `currency_status` `CURRENT`, with `public_access_suspended` and `high_value_committed`
    both false, `engagement_index` and `observed_demand_score` both 0.00, `usage_epochs`
    and `showcase_apps` both empty, `live_row_count` and `version_index_high_water` and
    `days_overdue` and `staleness_alert_count` all zero, and `last_published_at`,
    `next_due_at`, `last_staleness_alert_at` and `remediation_opened_at` all null."
    The PRD: "While the dataset's `publication_status` is `INVENTORIED`, `SCREENING` or
    `READY` — before its catalog page has any traffic worth trusting — the demand term is
    the coordinator's declared `public_demand_score` and the variant is `AS_DECLARED`."
    The PRD: "The three weighted terms are then added together and the finished sum is
    rounded half up to two decimal places exactly once, never term by term, giving
    `priority_score`." and "From that score, `priority_tier` follows on inclusive
    thresholds: `TIER_1` at 75.00 or above, `TIER_2` at 50.00 or above, and `TIER_3`
    otherwise."

    No dataset request is linked to this brand-new dataset, so community pressure is 0
    and the declared reading is 0.45 x 92.00 plus 0.35 x 96.00 plus 0.20 x 0 = 75.00,
    which lands exactly on the inclusive `TIER_1` threshold.

    Design: Corner/entities/dataset_creation_returns_declared_priority_and_initial_states
    """
    fixtures.reset_clock_to_start(api=api)
    department = fixtures.register_department(api=api)

    response = api.create_dataset(
        factories.dataset_payload(department["id"]),
        make_data_coordinator_headers(department["id"]),
    )
    dataset = validate_success(response, 201)
    assert_envelope_object(response.json())

    assert_common_fields(dataset, expected_version=1)
    assert_dataset_states(dataset, publication_status="INVENTORIED", currency_status="CURRENT")
    assert_priority(
        dataset,
        priority_score=75.00,
        priority_score_variant="AS_DECLARED",
        priority_tier="TIER_1",
    )
    assert_money(dataset["engagement_index"], 0.00, "engagement_index")
    assert_money(dataset["observed_demand_score"], 0.00, "observed_demand_score")
    assert dataset["public_access_suspended"] is False, (
        f"Expected public_access_suspended false, got {dataset['public_access_suspended']!r}"
    )
    assert dataset["high_value_committed"] is False, (
        f"Expected high_value_committed false, got {dataset['high_value_committed']!r}"
    )
    assert dataset["usage_epochs"] == [], (
        f"Expected an empty usage_epochs array, got {dataset['usage_epochs']!r}"
    )
    assert dataset["showcase_apps"] == [], (
        f"Expected an empty showcase_apps array, got {dataset['showcase_apps']!r}"
    )
    for field in ("live_row_count", "version_index_high_water", "days_overdue", "staleness_alert_count"):
        assert dataset[field] == 0, f"Expected {field} 0 on a new dataset, got {dataset[field]}"
    for field in ("last_published_at", "next_due_at", "last_staleness_alert_at", "remediation_opened_at"):
        assert dataset[field] is None, f"Expected {field} null on a new dataset, got {dataset[field]!r}"


def test_license_read_back_by_id_carries_stored_flags_and_attribution_reuse_class(api):
    """Reading a licence by id returns it exactly as stored, reuse class included.

    The PRD: "otherwise, if attribution is required, commercial use is allowed and
    share-alike is not required, the class is `ATTRIBUTION`" — the second clause of the
    first-match ladder, which is the one a licence with `attribution_required` true,
    `commercial_use_allowed` true and `share_alike` false falls into. The PRD: "A new
    licence has `retired` false." The PRD: "`version` (integer): a counter that starts at
    1 on creation and increments by exactly 1 on every mutation of that row, including
    mutations the server performs on its own initiative as a cascade from some other
    resource's transition."

    A read is not a mutation, so the licence still reports `version` 1 and its three
    stored booleans unchanged.

    Design: Corner/entities/license_retrieval_returns_stored_flags_and_reuse_class
    """
    fixtures.reset_clock_to_start(api=api)
    created = fixtures.create_license(api=api)

    response = api.get_license(created["id"], ANONYMOUS_HEADERS)
    licence = validate_success(response)
    assert_envelope_object(response.json())

    assert licence["id"] == created["id"], (
        f"Expected the licence with id {created['id']}, got {licence['id']}"
    )
    assert licence["code"] == "CC-BY-4.0", f"Expected code CC-BY-4.0, got {licence['code']}"
    assert licence["name"] == "Creative Commons Attribution 4.0", (
        f"Expected name 'Creative Commons Attribution 4.0', got {licence['name']}"
    )
    assert licence["attribution_required"] is True, (
        f"Expected attribution_required true, got {licence['attribution_required']!r}"
    )
    assert licence["commercial_use_allowed"] is True, (
        f"Expected commercial_use_allowed true, got {licence['commercial_use_allowed']!r}"
    )
    assert licence["share_alike"] is False, (
        f"Expected share_alike false, got {licence['share_alike']!r}"
    )
    assert licence["reuse_permission_class"] == "ATTRIBUTION", (
        f"Expected reuse_permission_class ATTRIBUTION, got {licence['reuse_permission_class']}"
    )
    assert licence["retired"] is False, f"Expected retired false, got {licence['retired']!r}"
    assert_common_fields(licence, expected_version=1)


def test_dataset_read_with_unknown_identifier_answers_dataset_not_found(api):
    """A well-formed identifier matching no dataset resolves to the 404 error envelope.

    The PRD: "Path resolution, on every endpoint that has path parameters: each addressed
    resource resolves, checked left to right (see §2.8), answering with the not-found code
    for the *first* unresolvable segment" — for a dataset path that code is named
    explicitly in the PRD: "a request naming a dataset that does not exist answers
    `ERR_DATASET_NOT_FOUND` without ever looking for the showcase entry, and only once the
    dataset resolves does a missing label answer `ERR_SHOWCASE_NOT_FOUND`."

    So the read is refused with `ERR_DATASET_NOT_FOUND` at 404 in the error envelope, not
    with an empty success body, and the failed lookup leaves the catalogue empty.

    Design: Corner/entities/dataset_retrieval_with_unknown_id_returns_not_found
    """
    fixtures.reset_clock_to_start(api=api)
    fixtures.register_department(api=api)

    response = api.get_dataset(NON_EXISTENT_UUID, ANONYMOUS_HEADERS)
    error = validate_error(response, ERR_DATASET_NOT_FOUND)

    body = response.json()
    assert body.get("response_type") == "error", (
        f"Expected response_type 'error', got {body.get('response_type')!r}"
    )
    assert isinstance(error.get("message"), str) and error["message"], (
        f"Expected a non-empty human-readable message, got {error.get('message')!r}"
    )

    rows, meta = validate_paginated(api.list_datasets(ANONYMOUS_HEADERS))
    assert meta["total_count"] == 0, (
        f"Expected total_count 0 after a failed lookup, got {meta['total_count']}"
    )
    assert rows == [], f"Expected no dataset rows after a failed lookup, got {rows!r}"


def test_dataset_creation_without_policy_value_score_is_rejected_as_invalid_request(api):
    """`policy_value_score` is a required creation input, so omitting it fails the shape check.

    The PRD: "Inventorying a dataset takes the owning `department_id` — which must equal
    the coordinator's own identity and is immutable thereafter — a catalog `title`, a
    unique lowercase kebab-case `slug`, a public catalog `description`, the declared
    `update_frequency` (one of `DAILY`, `WEEKLY`, `MONTHLY`, `QUARTERLY`, `ANNUAL` or
    `IRREGULAR`), the `column_count` of the extract as published, its `sensitivity_class`
    (`PUBLIC`, `SENSITIVE` or `RESTRICTED`), and two coordinator-declared judgements on a
    0.00-to-100.00 scale with two decimals: `public_demand_score` and
    `policy_value_score`."
    The PRD: "Request shape, on every write endpoint and on every paginated list endpoint:
    required fields present, enum members recognised, and numeric values inside their
    declared ranges" …

    That same precedence entry names the refusal as `ERR_INVALID_REQUEST` (400), and
    because it is a request-shape check nothing is persisted: the catalogue still holds no
    dataset afterwards.

    Design: Corner/entities/dataset_creation_missing_required_policy_value_score_returns_400
    """
    fixtures.reset_clock_to_start(api=api)
    department = fixtures.register_department(api=api)

    payload = factories.dataset_payload(department["id"])
    payload.pop("policy_value_score")

    response = api.create_dataset(payload, make_data_coordinator_headers(department["id"]))
    validate_error(response, ERR_INVALID_REQUEST)

    rows, meta = validate_paginated(api.list_datasets(ANONYMOUS_HEADERS))
    assert meta["total_count"] == 0, (
        f"Expected total_count 0 after a rejected create, got {meta['total_count']}"
    )
    assert rows == [], f"Expected no dataset rows after a rejected create, got {rows!r}"


def test_license_created_without_the_three_permission_flags_classifies_as_unrestricted(api):
    """The declared boolean defaults feed the first clause of the reuse-class ladder.

    The PRD: "three booleans — `attribution_required` (defaulting to false),
    `commercial_use_allowed` (defaulting to true) and `share_alike` (defaulting to false)"
    The PRD: "if attribution is not required, commercial use is allowed and share-alike is
    not required, the class is `UNRESTRICTED`"
    The PRD: "A new licence has `retired` false."

    A licence supplying only `code` and `name` therefore lands on false / true / false and
    matches the ladder's first clause, so its `reuse_permission_class` is `UNRESTRICTED`.

    Design: Corner/entities/license_creation_omitting_flags_applies_declared_defaults
    """
    fixtures.reset_clock_to_start(api=api)

    response = api.create_license(
        {"code": "CC0-1.0", "name": "Public Domain Dedication"}, PORTAL_ADMIN_HEADERS
    )
    licence = validate_success(response, 201)

    assert licence["attribution_required"] is False, (
        f"Expected the declared default attribution_required false, "
        f"got {licence['attribution_required']!r}"
    )
    assert licence["commercial_use_allowed"] is True, (
        f"Expected the declared default commercial_use_allowed true, "
        f"got {licence['commercial_use_allowed']!r}"
    )
    assert licence["share_alike"] is False, (
        f"Expected the declared default share_alike false, got {licence['share_alike']!r}"
    )
    assert licence["reuse_permission_class"] == "UNRESTRICTED", (
        f"Expected reuse_permission_class UNRESTRICTED, got {licence['reuse_permission_class']}"
    )
    assert licence["retired"] is False, f"Expected retired false, got {licence['retired']!r}"
    assert_common_fields(licence, expected_version=1)


def test_client_supplied_priority_and_engagement_values_are_discarded_on_dataset_creation(api):
    """Priority and engagement are computed by the portal, never accepted from the body.

    The PRD: "Prioritisation is what turns that inventory into a work queue, and it is
    computed the moment the dataset is created."
    The PRD: "The three weighted terms are then added together and the finished sum is
    rounded half up to two decimal places exactly once, never term by term, giving
    `priority_score`." and "From that score, `priority_tier` follows on inclusive
    thresholds: `TIER_1` at 75.00 or above, `TIER_2` at 50.00 or above, and `TIER_3`
    otherwise."
    The PRD: "A newly inventoried dataset sits at `publication_status` `INVENTORIED` and
    `currency_status` `CURRENT`, with `public_access_suspended` and `high_value_committed`
    both false, `engagement_index` and `observed_demand_score` both 0.00, `usage_epochs`
    and `showcase_apps` both empty, `live_row_count` and `version_index_high_water` and
    `days_overdue` and `staleness_alert_count` all zero, and `last_published_at`,
    `next_due_at`, `last_staleness_alert_at` and `remediation_opened_at` all null."

    The body smuggles `priority_score` 99.99, `priority_tier` `TIER_3` and
    `engagement_index` 88.00. The computed reading from the declared inputs is
    0.45 x 92.00 plus 0.35 x 96.00 = 75.00 at `TIER_1`, with engagement still 0.00, and
    that is what must be stored and returned.

    Design: Corner/entities/dataset_priority_fields_are_computed_input_ignored
    """
    fixtures.reset_clock_to_start(api=api)
    department = fixtures.register_department(api=api)

    payload = factories.dataset_payload(
        department["id"], priority_score=99.99, priority_tier="TIER_3", engagement_index=88.00
    )
    dataset = validate_success(
        api.create_dataset(payload, make_data_coordinator_headers(department["id"])), 201
    )

    assert_priority(
        dataset,
        priority_score=75.00,
        priority_score_variant="AS_DECLARED",
        priority_tier="TIER_1",
    )
    assert_money(dataset["engagement_index"], 0.00, "engagement_index")
    assert_money(dataset["observed_demand_score"], 0.00, "observed_demand_score")

    reread = fixtures.read_dataset(dataset["id"], api=api)
    assert_priority(
        reread,
        priority_score=75.00,
        priority_score_variant="AS_DECLARED",
        priority_tier="TIER_1",
    )
    assert_money(reread["engagement_index"], 0.00, "engagement_index")


def test_member_registration_mints_identity_and_base_reputation_ignoring_supplied_values(api):
    """Registration mints identity and reputation itself; supplied values are discarded.

    The PRD: "`id` (string): a server-minted UUID. It carries no type prefix and clients
    never supply it."
    The PRD: "`created_at` (string): an ISO 8601 UTC timestamp with three fractional
    digits, recording the logical instant the row was created."
    The PRD: "`version` (integer): a counter that starts at 1 on creation and increments
    by exactly 1 on every mutation of that row, including mutations the server performs on
    its own initiative as a cascade from some other resource's transition."
    The PRD: "A new member begins with `accepted_issue_count`, `rejected_issue_count`,
    `approved_showcase_count` and `decay_epochs` all zero, `reputation_score` 50.00,
    `vote_weight` 2, `status` `ACTIVE`, and `last_credited_at` initialised to the member's
    own `created_at`."

    The body smuggles an `id`, a 2020 `created_at`, `version` 42, `reputation_score`
    100.00 and `vote_weight` 3. With the logical clock standing at its starting instant,
    the row must come back with a server UUID other than the supplied one, `created_at`
    at that logical instant, `version` 1, and the base reputation of 50.00 at weight 2.

    Design: Corner/entities/member_registration_mints_system_fields_input_ignored
    """
    fixtures.reset_clock_to_start(api=api)

    smuggled_id = "11111111-1111-4111-8111-111111111111"
    payload = factories.member_payload(
        id=smuggled_id,
        created_at="2020-01-01T00:00:00.000Z",
        version=42,
        reputation_score=100.00,
        vote_weight=3,
    )
    member = validate_success(api.register_member(payload, ANONYMOUS_HEADERS), 201)

    assert_common_fields(member, expected_version=1)
    assert member["id"] != smuggled_id, (
        f"Expected a server-minted id different from the supplied {smuggled_id}, got {member['id']}"
    )
    assert member["created_at"].startswith("2026-08-01T00:00:00"), (
        f"Expected created_at at the logical instant 2026-08-01T00:00:00, "
        f"got {member['created_at']}"
    )
    assert_money(member["reputation_score"], 50.00, "reputation_score")
    assert member["vote_weight"] == 2, f"Expected vote_weight 2, got {member['vote_weight']}"
    assert member["status"] == "ACTIVE", f"Expected status ACTIVE, got {member['status']}"
    for field in (
        "accepted_issue_count",
        "rejected_issue_count",
        "approved_showcase_count",
        "decay_epochs",
    ):
        assert member[field] == 0, f"Expected {field} 0 on a new member, got {member[field]}"
    assert member["last_credited_at"] == member["created_at"], (
        f"Expected last_credited_at initialised to created_at {member['created_at']}, "
        f"got {member['last_credited_at']}"
    )
    assert member["email"] == "ana@civic.example", (
        f"Expected the supplied email ana@civic.example, got {member['email']}"
    )


def test_dataset_creation_with_an_undeclared_update_frequency_is_rejected_as_invalid_request(api):
    """`update_frequency` is a closed enumeration, so an unlisted member is refused.

    The PRD: "Inventorying a dataset takes the owning `department_id` — which must equal
    the coordinator's own identity and is immutable thereafter — a catalog `title`, a
    unique lowercase kebab-case `slug`, a public catalog `description`, the declared
    `update_frequency` (one of `DAILY`, `WEEKLY`, `MONTHLY`, `QUARTERLY`, `ANNUAL` or
    `IRREGULAR`), the `column_count` of the extract as published, its `sensitivity_class`
    (`PUBLIC`, `SENSITIVE` or `RESTRICTED`), and two coordinator-declared judgements on a
    0.00-to-100.00 scale with two decimals: `public_demand_score` and
    `policy_value_score`."
    The PRD: "Request shape, on every write endpoint and on every paginated list endpoint:
    required fields present, enum members recognised, and numeric values inside their
    declared ranges" …

    `FORTNIGHTLY` is not one of the six declared members, so the create is refused with
    `ERR_INVALID_REQUEST` (400) rather than stored verbatim; a second attempt differing
    only in a declared `WEEKLY` cadence is accepted, which shows the rejection cost the
    slug nothing.

    Design: Corner/entities/dataset_creation_with_unknown_update_frequency_returns_4XX
    """
    fixtures.reset_clock_to_start(api=api)
    department = fixtures.register_department(api=api)
    coordinator_headers = make_data_coordinator_headers(department["id"])

    rejected = api.create_dataset(
        factories.dataset_payload(department["id"], update_frequency="FORTNIGHTLY"),
        coordinator_headers,
    )
    validate_error(rejected, ERR_INVALID_REQUEST)

    rows, meta = validate_paginated(api.list_datasets(ANONYMOUS_HEADERS))
    assert meta["total_count"] == 0, (
        f"Expected total_count 0 after a rejected cadence, got {meta['total_count']}"
    )
    assert rows == [], f"Expected no dataset rows after a rejected cadence, got {rows!r}"

    accepted = validate_success(
        api.create_dataset(
            factories.dataset_payload(department["id"], update_frequency="WEEKLY"),
            coordinator_headers,
        ),
        201,
    )
    assert accepted["update_frequency"] == "WEEKLY", (
        f"Expected update_frequency WEEKLY on the accepted create, got {accepted['update_frequency']}"
    )


def test_dataset_creation_naming_an_unknown_department_answers_department_not_found(api):
    """An unresolvable `department_id` in the body outranks the coordinator scope check.

    The PRD: "Many operations are guarded by several independent checks at once, and which
    error a caller sees is part of the contract."
    The PRD: "Body foreign keys, on `POST /open-data/datasets`,
    `POST /open-data/metadata-records`, `POST /open-data/privacy-assessments`,
    `POST /open-data/publication-pipelines`, `POST /open-data/pipeline-runs`,
    `POST /open-data/dataset-versions`, `POST /open-data/quality-issues`,
    `POST /open-data/dataset-requests`, `POST /open-data/dataset-requests/{requestId}/votes`,
    `POST /open-data/dataset-requests/{requestId}/fulfill`,
    `POST /open-data/quality-issues/{issueId}/link-correction` and
    `POST /open-data/datasets/{datasetId}/showcase-apps`: every foreign key supplied in the
    body resolves to an existing row — otherwise the corresponding 404 from the same family
    as priority 3 (`ERR_DEPARTMENT_NOT_FOUND`, `ERR_DATASET_NOT_FOUND`,
    `ERR_LICENSE_NOT_FOUND`, `ERR_RUNNER_NOT_FOUND`, `ERR_MEMBER_NOT_FOUND`,
    `ERR_VERSION_NOT_FOUND`, `ERR_ISSUE_NOT_FOUND` or `ERR_PIPELINE_NOT_FOUND`)."
    The PRD: "Departmental scope, on every `DataCoordinator`-only endpoint:
    `ERR_DEPARTMENT_SCOPE_VIOLATION` (403) as described in §2.1."

    The body foreign-key check is priority 5 and the departmental scope check is priority
    6, so the body's unresolvable `department_id` decides the answer: `ERR_DEPARTMENT_NOT_FOUND`
    at 404, never `ERR_DEPARTMENT_SCOPE_VIOLATION` at 403 — here the coordinator's identity
    equals the same unknown id, so only the referential check can fire first.

    Design: Corner/entities/dataset_creation_with_unknown_department_returns_not_found
    """
    fixtures.reset_clock_to_start(api=api)
    fixtures.register_department(api=api)

    response = api.create_dataset(
        factories.dataset_payload(NON_EXISTENT_UUID),
        make_data_coordinator_headers(NON_EXISTENT_UUID),
    )
    validate_error(response, ERR_DEPARTMENT_NOT_FOUND)

    rows, meta = validate_paginated(api.list_datasets(ANONYMOUS_HEADERS))
    assert meta["total_count"] == 0, (
        f"Expected total_count 0 after a rejected create, got {meta['total_count']}"
    )
    assert rows == [], f"Expected no dataset rows after a rejected create, got {rows!r}"


def test_fulfilling_an_accepted_request_transfers_community_pressure_onto_the_dataset(api):
    """Fulfilment is the edge that carries community demand onto a catalogue entry.

    The PRD: "The request moves `ACCEPTED → FULFILLED`, its `linked_dataset_id` is set to
    that dataset, and the linked dataset's community-pressure input and `priority_score`
    are recomputed under whichever variant its current `priority_score_variant` names."
    The PRD: "take every dataset request whose `linked_dataset_id` is this dataset and
    whose `status` is either `ACCEPTED` or `FULFILLED` — requests still `OPEN`, still
    `UNDER_REVIEW`, or `DECLINED` contribute nothing, and there is no time window, so
    every qualifying row counts — sum their `weighted_vote_total` values, multiply that sum
    by 4, and cap the result at 100."
    The PRD: "`weighted_vote_total` is then the plain sum of every stored `weight` across
    the whole array with no time window, and `demand_signal` is that total multiplied by 5,
    capped at 100, and rounded half up to two decimal places."
    The PRD: "`vote_weight` follows on inclusive thresholds: 3 when `reputation_score` is
    at least 70.00, 2 when it is at least 40.00 but below 70.00, and 1 below 40.00."
    The PRD: "Once the dataset's `publication_status` is `PUBLISHED` or
    `UNDER_REMEDIATION`, the demand term becomes the measured `observed_demand_score` and
    the variant is `AS_OBSERVED`."

    Two freshly registered members hold reputation 50.00 and therefore weight 2 each, so
    the request carries `weighted_vote_total` 4 and `demand_signal` 20.00. The published
    dataset has no usage epochs, so before fulfilment its observed reading is
    0.45 x 0.00 plus 0.35 x 96.00 plus 0.20 x 0 = 33.60. Linking the request contributes
    community pressure of 4 x 4 = 16, lifting the score to 0.45 x 0.00 plus 0.35 x 96.00
    plus 0.20 x 16 = 36.80, still `TIER_3`, and the dataset's own lifecycle state is
    untouched.

    Design: Corner/entities/fulfilled_request_transfers_community_pressure_across_aggregates
    """
    ctx = fixtures.setup_published_dataset(api=api, credit_units=0)
    first = fixtures.setup_member(api=api)
    second = fixtures.setup_member(
        api=api, email="ben@civic.example", display_name="Ben Mapper"
    )

    request = fixtures.open_dataset_request(first["member_id"], api=api)
    fixtures.cast_vote(request["id"], first["member_id"], api=api)
    fixtures.cast_vote(request["id"], second["member_id"], api=api)

    voted = validate_success(api.get_dataset_request(request["id"], ANONYMOUS_HEADERS))
    assert voted["weighted_vote_total"] == 4, (
        f"Expected weighted_vote_total 4 from two weight-2 members, "
        f"got {voted['weighted_vote_total']}"
    )
    assert_money(voted["demand_signal"], 20.00, "demand_signal")

    fixtures.review_request(request["id"], api=api)
    fixtures.decide_request(request["id"], "ACCEPT", api=api)

    before = fixtures.read_dataset(ctx["dataset_id"], api=api)
    assert_priority(
        before,
        priority_score=33.60,
        priority_score_variant="AS_OBSERVED",
        priority_tier="TIER_3",
    )

    fulfilled = validate_success(
        api.fulfill_dataset_request(
            request["id"], factories.fulfill_payload(ctx["dataset_id"]), PORTAL_ADMIN_HEADERS
        )
    )
    assert fulfilled["status"] == "FULFILLED", (
        f"Expected request status FULFILLED, got {fulfilled['status']}"
    )
    assert fulfilled["linked_dataset_id"] == ctx["dataset_id"], (
        f"Expected linked_dataset_id {ctx['dataset_id']}, got {fulfilled['linked_dataset_id']}"
    )

    after = fixtures.read_dataset(ctx["dataset_id"], api=api)
    assert_priority(
        after,
        priority_score=36.80,
        priority_score_variant="AS_OBSERVED",
        priority_tier="TIER_3",
    )
    assert_dataset_states(after, publication_status="PUBLISHED")
