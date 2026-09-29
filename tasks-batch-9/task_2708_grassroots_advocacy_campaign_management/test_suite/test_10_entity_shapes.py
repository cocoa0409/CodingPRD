"""Row shapes: what a create returns, what it refuses, and what a read omits.

Declared defaults, server-minted identity fields, computed fields that may not be
supplied, required fields, enum sets, parent resolution, listing windows and the
one entity that carries no version at all.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_CAMPAIGN_MISMATCH,
    ERR_CAMPAIGN_NOT_FOUND,
    ERR_DISTRICT_MISMATCH,
    ERR_INVALID_REQUEST,
    ERR_LEGISLATOR_NOT_FOUND,
    ERR_SPOKESPERSON_NOT_CERTIFIED,
)
from test_helpers.assertions import (
    assert_absent_or_none,
    assert_cents,
    assert_common_fields,
    assert_consent_event_fields,
    assert_count,
    assert_envelope_metadata,
    assert_field,
    assert_page,
    assert_score,
    assert_utc_millis_timestamp,
    assert_version_is,
)
from test_helpers.test_users import (
    make_campaign_director_headers,
    make_compliance_officer_headers,
    make_field_organizer_headers,
)
from test_helpers.types import (
    ACQUISITION_DIGITAL_AD,
    ACQUISITION_EVENT,
    CAMPAIGN_DRAFT,
    CHANNEL_EMAIL,
    CHANNEL_PHONE,
    CONSENT_ACTION_GRANT,
    CONSENT_ACTION_REVOKE,
    CONSENT_NONE,
    CONSENT_REVOKED,
    LAWFUL_BASIS_EVENT_CARD,
    MILESTONE_FLOOR_VOTE,
    POSTURE_OPEN,
    POSTURE_OVERRIDE_NONE,
    PUBLICATION_CONSENT_PUBLIC,
    STANCE_UNDECIDED,
    TIER_MONITOR,
)


def test_a_new_campaign_lands_in_draft_with_every_counter_at_zero(api):
    """No supplied field silently seeds a computed one.

    PRD: "A freshly created campaign lands in `status` `DRAFT`, `posture` `OPEN` and `posture_override` `NONE`."

    Design: Corner/entities/campaign_create_returns_envelope_and_declared_defaults
    """
    fx.park_clock(api)

    response = api.create_campaign(F.campaign_payload(),
                                   headers=make_campaign_director_headers())

    assert_envelope_metadata(response)
    campaign = validate_success(response, expected_status=201)
    assert_field(campaign, "status", CAMPAIGN_DRAFT)
    assert_field(campaign, "posture", POSTURE_OPEN)
    assert_field(campaign, "posture_override", POSTURE_OVERRIDE_NONE)
    assert_count(campaign["blocked_activation_count"], 0)
    assert_count(campaign["opposed_priority_legislator_count"], 0)
    assert_count(campaign["total_actions_logged"], 0)
    assert_count(campaign["distinct_acting_supporter_count"], 0)
    assert_cents(campaign["committed_share_total_cents"], 0)
    assert_cents(campaign["funded_total_cents"], 100000)


def test_the_server_mints_the_identity_block_from_the_logical_clock(api):
    """A bare UUID, the clock's instant to three digits, and version 1.

    PRD: "Most resources additionally carry `updated_at`, an ISO 8601 UTC timestamp refreshed on every mutation of that row, and `version`, an integer that begins at 1 on creation and increments by exactly 1 on every mutation of that row — including mutations the caller did not ask for directly, such as a counter recomputed as a cascade hop of some other entity's transition."

    Design: Corner/entities/campaign_system_fields_minted_by_server_on_create
    """
    fx.park_clock(api, C.CLOCK_DEFAULT_UTC)

    campaign = fx.create_draft_campaign(api)

    assert_common_fields(campaign)
    assert_version_is(campaign, 1)
    assert_field(campaign, "created_at", "2026-08-01T00:00:00.000Z")
    assert_field(campaign, "updated_at", "2026-08-01T00:00:00.000Z")
    reread = fx.read_campaign(api, campaign["id"])
    assert_field(reread, "id", campaign["id"])
    assert_field(reread, "created_at", campaign["created_at"])
    assert_version_is(reread, 1)


def test_a_client_supplied_posture_is_an_unknown_field(api):
    """Posture is derived, so naming it in the body is malformed input.

    PRD: "The body is well formed: no unknown fields, every required field present, every enum value inside its declared set, integers non-negative where declared non-negative, cent amounts integral, and timestamps parseable as ISO 8601 UTC — otherwise `ERR_INVALID_REQUEST`."

    Design: Corner/entities/campaign_create_rejects_client_supplied_computed_posture
    """
    fx.park_clock(api)

    response = api.create_campaign(F.campaign_payload(posture="FROZEN"),
                                   headers=make_campaign_director_headers())

    validate_error(response, ERR_INVALID_REQUEST, expected_status=422)
    assert_page(api.list_campaigns(headers=make_campaign_director_headers()),
                expected_total=0)


def test_a_campaign_without_a_goal_statement_is_refused(api):
    """The goal statement has no default, so omitting it is malformed input.

    PRD: "The payload names the campaign — `name`, non-empty and at most 160 characters — and states what it is trying to achieve: `goal_statement`, a single sentence of at most 400 characters describing what the decision makers must do, and `bill_reference`, at most 40 characters, naming the legislative vehicle being targeted (for instance "HB-1420")."

    Design: Corner/entities/campaign_create_missing_goal_statement_returns_invalid_request
    """
    fx.park_clock(api)
    payload = F.campaign_payload()
    del payload["goal_statement"]

    response = api.create_campaign(payload,
                                   headers=make_campaign_director_headers())

    validate_error(response, ERR_INVALID_REQUEST, expected_status=422)
    assert_page(api.list_campaigns(headers=make_campaign_director_headers()),
                expected_total=0)


def test_a_stance_outside_the_declared_set_is_refused(api):
    """HOSTILE is not a whip-count position this contract recognises.

    PRD: "An opening whip-count `stance` may be supplied from `SUPPORT`, `LEAN_SUPPORT`, `UNDECIDED`, `LEAN_OPPOSE` and `OPPOSE`; when omitted the stance is `UNDECIDED`."

    Design: Corner/entities/legislator_create_with_stance_outside_enum_returns_invalid_request
    """
    campaign = fx.create_draft_campaign(api)

    response = api.create_legislator(
        F.legislator_payload(campaign["id"], stance="HOSTILE"),
        headers=make_campaign_director_headers())

    validate_error(response, ERR_INVALID_REQUEST, expected_status=422)
    assert_page(api.list_legislators(headers=make_campaign_director_headers(),
                                     params={"campaign_id": campaign["id"]}),
                expected_total=0)


def test_an_unknown_legislator_id_is_a_not_found_rather_than_an_empty_body(api):
    """Each entity family has its own 404 code, and the store stays readable.

    PRD: "Twelve entity families each have their own HTTP 404 code: `ERR_CAMPAIGN_NOT_FOUND`, `ERR_MILESTONE_NOT_FOUND`, `ERR_LEGISLATOR_NOT_FOUND`, `ERR_SUPPORTER_NOT_FOUND`, `ERR_SEGMENT_NOT_FOUND`, `ERR_VARIANT_NOT_FOUND`, `ERR_PARTNER_NOT_FOUND`, `ERR_ENDORSEMENT_NOT_FOUND`, `ERR_ACTIVATION_NOT_FOUND`, `ERR_ACTION_RECORD_NOT_FOUND`, `ERR_SPOKESPERSON_NOT_FOUND` and `ERR_MEETING_NOT_FOUND`."

    Design: Corner/entities/legislator_get_with_unknown_id_returns_legislator_not_found
    """
    campaign = fx.create_draft_campaign(api)
    real = fx.add_legislator(api, campaign["id"])

    response = api.get_legislator(C.UNKNOWN_UUID,
                                  headers=make_campaign_director_headers())

    validate_error(response, ERR_LEGISLATOR_NOT_FOUND, expected_status=404)
    validate_success(api.get_legislator(
        real["id"], headers=make_campaign_director_headers()))


def test_an_omitted_stance_defaults_and_is_snapshotted_into_initial_stance(api):
    """The opening position is recorded twice so movement can be measured.

    PRD: "A new legislator starts with `contact_pressure_score` of 0.00, `priority_tier` `MONITOR`, `constituent_action_count` of 0 and `meeting_held_count` of 0."

    Design: Corner/entities/legislator_create_returns_initial_stance_snapshot_and_monitor_tier
    """
    campaign = fx.create_draft_campaign(api)
    payload = F.legislator_payload(campaign["id"])
    del payload["stance"]

    legislator = validate_success(
        api.create_legislator(payload, headers=make_field_organizer_headers()),
        expected_status=201)

    assert_field(legislator, "stance", STANCE_UNDECIDED)
    assert_field(legislator, "initial_stance", STANCE_UNDECIDED)
    assert_field(legislator, "priority_tier", TIER_MONITOR)
    assert_score(legislator["contact_pressure_score"], 0.00)
    assert_count(legislator["constituent_action_count"], 0)
    assert_count(legislator["meeting_held_count"], 0)
    assert_version_is(legislator, 1)


def test_a_supporter_enrolled_without_consent_sits_at_none_on_every_channel(api):
    """An empty consent log resolves to NONE, which is not suppression.

    PRD: "For each of the three channels `EMAIL`, `SMS` and `PHONE`, the server gathers every consent event of that supporter whose `channel` is either that channel or the wildcard `ALL`."

    Design: Corner/entities/supporter_create_without_consent_channels_defaults_every_channel_to_none
    """
    world = fx.create_active_campaign(api)

    supporter = validate_success(api.create_supporter({
        "campaign_id": world["campaign_id"],
        "full_name": "Quiet Quinn",
        "email": "quinn@example.org",
        "district_code": "HD-14",
        "acquisition_source": ACQUISITION_DIGITAL_AD,
    }, headers=make_field_organizer_headers()), expected_status=201)

    assert_field(supporter, "email_consent_state", CONSENT_NONE)
    assert_field(supporter, "sms_consent_state", CONSENT_NONE)
    assert_field(supporter, "phone_consent_state", CONSENT_NONE)
    assert_field(supporter, "suppressed", False)
    assert_count(supporter["consent_event_count"], 0)
    assert_absent_or_none(supporter, "phone")
    assert_count(supporter["touches_reserved"], 0)
    assert_page(api.list_supporter_consent_events(
        supporter["id"], headers=make_compliance_officer_headers()),
        expected_total=0)


def test_the_consent_log_is_append_only_and_numbered_monotonically(api):
    """Two appended events take sequence 1 then 2 and carry no version.

    PRD: "`ConsentEvent` is the one exception, and it is deliberate: consent events are immutable append-only records, so a consent event carries only `id` and `created_at`."

    Design: Corner/entities/consent_event_is_append_only_with_monotonic_sequence_no
    """
    world = fx.create_active_campaign(api)
    supporter = validate_success(api.create_supporter({
        "campaign_id": world["campaign_id"],
        "full_name": "Quiet Quinn",
        "email": "quinn@example.org",
        "district_code": "HD-14",
        "acquisition_source": ACQUISITION_DIGITAL_AD,
    }, headers=make_field_organizer_headers()), expected_status=201)

    first = fx.append_consent(api, supporter["id"], CHANNEL_EMAIL,
                              CONSENT_ACTION_GRANT,
                              source_reference="web-form-9")
    second = fx.append_consent(api, supporter["id"], CHANNEL_EMAIL,
                               CONSENT_ACTION_REVOKE,
                               source_reference="unsubscribe-link")

    assert_consent_event_fields(first)
    assert_count(first["sequence_no"], 1)
    assert_count(second["sequence_no"], 2)
    assert_utc_millis_timestamp(first["effective_at"])
    assert_field(first, "effective_at", "2026-08-01T00:00:00.000Z")
    reread = fx.read_supporter(api, supporter["id"])
    assert_count(reread["consent_event_count"], 2)
    assert_field(reread, "email_consent_state", CONSENT_REVOKED)


def test_a_milestone_under_an_unknown_campaign_fails_before_window_arithmetic(api):
    """Parent resolution sits above window sanity on the ladder.

    PRD: "Every foreign key supplied in the request body resolves, checked in the field order the endpoint declares — otherwise the matching not-found code."

    Design: Corner/entities/milestone_create_under_unknown_campaign_returns_campaign_not_found
    """
    campaign = fx.create_draft_campaign(api)

    response = api.create_milestone(
        F.milestone_payload(C.UNKNOWN_UUID, "2027-01-05T00:00:00Z",
                            "2027-01-04T00:00:00Z", kind=MILESTONE_FLOOR_VOTE,
                            label="House floor vote"),
        headers=make_campaign_director_headers())

    validate_error(response, ERR_CAMPAIGN_NOT_FOUND, expected_status=404)
    assert_page(api.list_campaign_milestones(
        campaign["id"], headers=make_campaign_director_headers()),
        expected_total=0)


def test_a_filtered_list_reports_the_filtered_total_not_the_page(api):
    """total_count counts matching rows before the window is applied.

    PRD: "List responses populate four pagination fields inside `meta`: `limit` and `offset` echo the effective values applied to the query, `total_count` reports the number of rows matching the filters before the page window is applied, and `has_more` is true exactly when rows remain beyond the current window."

    Design: Corner/entities/supporter_list_filter_and_pagination_report_total_count_and_has_more
    """
    world = fx.create_active_campaign(api)
    fx.add_supporter(api, world["campaign_id"], full_name="Sup 1",
                     email="s1@example.org", consent_source_reference="web-form-1")
    event_supporter = fx.add_supporter(
        api, world["campaign_id"], full_name="Sup 2", email="s2@example.org",
        acquisition_source=ACQUISITION_EVENT,
        consent_source_reference="web-form-2")
    fx.add_supporter(api, world["campaign_id"], full_name="Sup 3",
                     email="s3@example.org", consent_source_reference="web-form-3")

    headers = make_campaign_director_headers()
    base = {"campaign_id": world["campaign_id"]}
    assert_page(api.list_supporters(headers=headers,
                                    params=dict(base, limit=2, offset=0)),
                expected_total=3, expected_len=2, expected_has_more=True,
                expected_limit=2, expected_offset=0)
    assert_page(api.list_supporters(headers=headers,
                                    params=dict(base, limit=2, offset=2)),
                expected_total=3, expected_len=1, expected_has_more=False)
    rows, _ = assert_page(api.list_supporters(
        headers=headers, params=dict(base, acquisition_source=ACQUISITION_EVENT)),
        expected_total=1, expected_len=1, expected_has_more=False)
    assert_field(rows[0], "id", event_supporter["id"])


def test_a_meeting_naming_a_legislator_of_another_campaign_is_a_scope_mismatch(api):
    """All the ids resolve and the districts agree; the campaigns do not.

    PRD: "This rung guards five operations: activation creation, endorsement creation, district-meeting creation, action-record creation and segment creation."

    Design: Corner/entities/district_meeting_naming_a_legislator_of_another_campaign_returns_campaign_mismatch
    """
    first = fx.create_active_campaign(api)
    supporter = fx.add_supporter(
        api, first["campaign_id"], channels=[CHANNEL_EMAIL, CHANNEL_PHONE],
        full_name="Tess Teller", email="tess@example.org",
        phone="+15551230022", acquisition_source=ACQUISITION_EVENT,
        lawful_basis=LAWFUL_BASIS_EVENT_CARD,
        consent_source_reference="townhall-card-7")
    profile = fx.create_certified_spokesperson(
        api, supporter["id"],
        story_summary="Lost her lease after a 40 percent rent increase.",
        publication_consent=PUBLICATION_CONSENT_PUBLIC)
    other = fx.create_draft_campaign(api, name="Rent Stabilisation Now")
    other_legislator = fx.add_legislator(api, other["id"],
                                         full_name="Rep. Bell")

    response = api.create_meeting(
        F.meeting_payload(first["campaign_id"], other_legislator["id"],
                          profile["id"], "2026-08-10T14:00:00Z",
                          "2026-08-10T15:00:00Z"),
        headers=make_field_organizer_headers())

    validate_error(response, ERR_CAMPAIGN_MISMATCH, expected_status=422)
    body = response.json()["data"]
    assert body["error_id"] not in (ERR_DISTRICT_MISMATCH,
                                    ERR_SPOKESPERSON_NOT_CERTIFIED)
    assert_page(api.list_meetings(headers=make_field_organizer_headers(),
                                  params={"campaign_id": first["campaign_id"]}),
                expected_total=0)
