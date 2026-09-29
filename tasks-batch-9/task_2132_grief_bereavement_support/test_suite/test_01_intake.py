"""Intake: filing, screening, declining and accepting referrals, plus the
request envelope, pagination and the logical clock's declared startup instant."""

import pytest

from test_helpers import (
    IC,
    PD,
    RS,
    ApiErrorId,
    UNUSED_UUIDS,
    accept_referral,
    api_client,
    assert_bare_uuid,
    assert_iso_millis,
    assert_participant,
    assert_referral,
    create_participant,
    create_referral,
    create_referral_payload,
    headers_without_role,
    read_participant,
    read_referral,
    screen_referral,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_referral_create_returns_201_with_null_screening_fields():
    """PRD 3.1: "A newly filed referral lands in status `RECEIVED` with
    `screening_band` and `days_since_death` both null, `eligibility_note`,
    `decline_reason` and `participant_id` all null."

    Design: Corner/entities/referral_create_returns_201_with_system_fields_populated
    """
    set_clock()
    resp = api_client.create_referral(
        create_referral_payload(
            source_type="HOSPICE", source_org_name="Riverside Hospice",
            decedent_name="Ann Vance", date_of_death="2026-06-01",
            relationship_to_deceased="SPOUSE", loss_type="ANTICIPATED_ILLNESS",
            contact_name="Ben Vance", contact_email="ben.vance@example.org"),
        RS)
    data = validate_success(resp, 201)
    assert_referral(data)
    assert data["status"] == "RECEIVED", f"Expected RECEIVED, got {data['status']}"
    assert data["screening_band"] is None
    assert data["days_since_death"] is None
    assert data["eligibility_note"] is None
    assert data["decline_reason"] is None
    assert data["participant_id"] is None


def test_referral_create_mints_a_bare_uuid_at_version_one():
    """PRD 2.4: "Every resource in this system is identified by a server-minted
    UUID exposed as `id`. Identifiers carry no type prefix and are never supplied
    by a client."
    PRD 2.4: "Every resource also carries `created_at`, an ISO 8601 UTC timestamp
    with three fractional digits recording when the record was first persisted."

    Design: Corner/entities/referral_create_returns_201_with_system_fields_populated
    """
    set_clock()
    data = validate_success(
        api_client.create_referral(create_referral_payload(), RS), 201)
    assert_bare_uuid(data["id"], "referral.id")
    assert_iso_millis(data["created_at"], "referral.created_at")
    assert data["version"] == 1, f"Expected version 1, got {data['version']}"


def test_referral_create_without_contact_email_is_rejected():
    """PRD 3.1: "and how to reach the bereaved contact (`contact_name` and
    `contact_email`)"
    PRD 2.5: "The body conforms to the endpoint's declared input: every required
    field is present, every enum value is a declared member, every integer lies
    inside its declared range, and every array-typed field is an array."
    PRD 2.5: "Any violation yields `ERR_INVALID_REQUEST` (422)."

    Design: Corner/entities/referral_create_missing_required_contact_email_returns_invalid_request
    """
    set_clock()
    payload = {
        "source_type": "SELF", "decedent_name": "Ann Vance",
        "date_of_death": "2026-06-01", "relationship_to_deceased": "SPOUSE",
        "loss_type": "ANTICIPATED_ILLNESS", "contact_name": "Ben Vance",
    }
    resp = api_client.create_referral(payload, RS)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value, 422)
    rows, meta = validate_paginated(api_client.list_referrals(IC))
    assert meta["total_count"] == 0, "no referral may be persisted by a rejected filing"


def test_hospice_referral_without_source_org_name_is_rejected():
    """PRD 2.5: "`source_org_name` is required when `source_type` is anything
    other than `SELF` and must be omitted or null when `source_type` is `SELF`"
    PRD 2.5: "Any violation yields `ERR_INVALID_REQUEST` (422)."

    Design: Corner/entities/referral_from_hospice_without_source_org_name_returns_invalid_request
    """
    set_clock()
    payload = {
        "source_type": "HOSPICE", "decedent_name": "Ann Vance",
        "date_of_death": "2026-06-01", "relationship_to_deceased": "SPOUSE",
        "loss_type": "ANTICIPATED_ILLNESS", "contact_name": "Ben Vance",
        "contact_email": "ben.vance@example.org",
    }
    validate_error(api_client.create_referral(payload, RS),
                   ApiErrorId.ERR_INVALID_REQUEST.value, 422)


def test_accepting_a_referral_copies_its_clinical_facts_to_the_participant():
    """PRD 3.1: "The new participant carries `referral_id` pointing back at the
    intake record, and copies four values verbatim from it: `contact_name` becomes
    the participant's `display_name`, and `loss_type`, `relationship_to_deceased`
    and `date_of_death` are carried across unchanged. The month-and-day slice of
    `date_of_death` is stored as `anniversary_month_day` in `MM-DD` form."
    PRD 3.1: "Because a person is being created rather than an existing record
    edited, acceptance answers with HTTP 201."

    Design: Corner/entities/participant_system_fields_are_copied_from_the_accepted_referral
    """
    set_clock()
    referral = create_referral(
        source_type="HOSPICE", source_org_name="Riverside Hospice",
        decedent_name="Baby Nolan", date_of_death="2026-06-01",
        relationship_to_deceased="PARENT", loss_type="PERINATAL",
        contact_name="Ida Nolan", contact_email="ida.nolan@example.org")
    screen_referral(referral["id"])

    data = validate_success(api_client.accept_referral(referral["id"], IC), 201)
    assert_participant(data)
    assert data["referral_id"] == referral["id"]
    assert data["loss_type"] == "PERINATAL"
    assert data["relationship_to_deceased"] == "PARENT"
    assert data["date_of_death"] == "2026-06-01"
    assert data["anniversary_month_day"] == "06-01"
    assert data["display_name"] == "Ida Nolan"
    assert data["service_status"] == "INTAKE"
    assert data["outreach_status"] == "SCHEDULED"
    assert data["risk_tier"] == "LOW"

    refreshed = read_referral(referral["id"])
    assert refreshed["status"] == "ACCEPTED"
    assert refreshed["participant_id"] == data["id"]


def test_participant_read_with_unknown_id_is_not_found():
    """PRD 2.8: "Each entity has its own dedicated code — `ERR_REFERRAL_NOT_FOUND`,
    `ERR_PARTICIPANT_NOT_FOUND`"

    Design: Corner/entities/participant_read_with_unknown_id_returns_participant_not_found
    """
    set_clock()
    validate_error(
        api_client.get_participant(UNUSED_UUIDS["participant"], IC),
        ApiErrorId.ERR_PARTICIPANT_NOT_FOUND.value, 404)


def test_accepting_an_unscreened_referral_is_refused():
    """PRD 3.1: "Accepting, by contrast, is available only from `SCREENED`;
    attempting it against a referral in any other status is refused with
    `ERR_REFERRAL_NOT_SCREENED`."

    Design: Corner/state_machines/referral_accept_without_screening_returns_referral_not_screened
    """
    set_clock()
    referral = create_referral(source_type="SELF", decedent_name="Elin Roos",
                               date_of_death="2026-05-20",
                               relationship_to_deceased="SPOUSE",
                               loss_type="SUDDEN_DEATH", contact_name="Finn Roos",
                               contact_email="finn.roos@example.org")
    validate_error(api_client.accept_referral(referral["id"], IC),
                   ApiErrorId.ERR_REFERRAL_NOT_SCREENED.value, 409)

    refreshed = read_referral(referral["id"])
    assert refreshed["status"] == "RECEIVED"
    assert refreshed["participant_id"] is None
    rows, meta = validate_paginated(api_client.list_participants(IC))
    assert meta["total_count"] == 0, "a refused acceptance must mint no participant"


def test_declining_a_declined_referral_is_already_terminal():
    """PRD 3.1: "Both `ACCEPTED` and `DECLINED` are terminal for a referral: any
    further transition attempt out of either is refused with
    `ERR_ALREADY_TERMINAL`."

    Design: Corner/state_machines/referral_decline_twice_second_call_returns_already_terminal
    """
    set_clock()
    referral = create_referral(source_type="SELF", decedent_name="Elin Roos",
                               date_of_death="2026-05-20",
                               relationship_to_deceased="SPOUSE",
                               loss_type="SUDDEN_DEATH", contact_name="Finn Roos",
                               contact_email="finn.roos@example.org")
    screen_referral(referral["id"], "out of catchment")
    validate_success(
        api_client.decline_referral(referral["id"], {"decline_reason": "OUT_OF_AREA"}, IC))

    validate_error(
        api_client.decline_referral(referral["id"], {"decline_reason": "DUPLICATE"}, IC),
        ApiErrorId.ERR_ALREADY_TERMINAL.value, 409)

    refreshed = read_referral(referral["id"])
    assert refreshed["status"] == "DECLINED"
    assert refreshed["decline_reason"] == "OUT_OF_AREA", (
        "the first decline reason must survive the refused second attempt")


def test_screening_at_exactly_thirty_days_bands_urgent():
    """PRD 3.1: "Screening computes `days_since_death` as the whole number of days
    between `date_of_death` and the logical clock date, and from that number it
    bands the referral into `screening_band`."
    PRD 3.1: "Both thresholds are inclusive: exactly thirty days is still
    `URGENT`, and exactly one hundred and eighty days is still `PRIORITY`."

    Design: Corner/state_machines/referral_screening_stamps_band_and_days_since_death
    """
    set_clock()
    referral = create_referral(
        source_type="HOSPICE", source_org_name="Riverside Hospice",
        decedent_name="Otto Lind", date_of_death="2026-08-02",
        relationship_to_deceased="SPOUSE", loss_type="ANTICIPATED_ILLNESS",
        contact_name="Pia Lind", contact_email="pia.lind@example.org")

    data = validate_success(
        api_client.screen_referral(referral["id"], {"eligibility_note": "recent loss"}, IC))
    assert data["days_since_death"] == 30, (
        f"Expected 30 days since death, got {data['days_since_death']}")
    assert data["screening_band"] == "URGENT"
    assert data["status"] == "SCREENED"
    assert data["eligibility_note"] == "recent loss"


def test_screening_at_thirty_one_days_bands_priority():
    """PRD 3.1: "A death within the last month — thirty days or fewer since it
    occurred — bands as `URGENT`. A death older than that but no more than six
    months ago, meaning up to and including one hundred and eighty days, bands as
    `PRIORITY`."

    Design: Corner/state_machines/referral_screening_band_is_priority_at_thirty_one_days
    """
    set_clock()
    referral = create_referral(
        source_type="HOSPICE", source_org_name="Riverside Hospice",
        decedent_name="Quinn Marsh", date_of_death="2026-08-01",
        relationship_to_deceased="CHILD", loss_type="ANTICIPATED_ILLNESS",
        contact_name="Rune Marsh", contact_email="rune.marsh@example.org")

    data = validate_success(
        api_client.screen_referral(referral["id"], {"eligibility_note": "recent loss"}, IC))
    assert data["days_since_death"] == 31
    assert data["screening_band"] == "PRIORITY"


def test_filing_a_death_dated_after_the_logical_clock_is_refused():
    """PRD 3.1: "A death cannot be recorded in the future: if `date_of_death` is
    later than the logical clock date, the filing is refused with
    `ERR_DECEASED_DATE_IN_FUTURE`."

    Design: Corner/validations/referral_with_a_future_date_of_death_returns_deceased_date_in_future
    """
    set_clock()
    resp = api_client.create_referral(
        {"source_type": "SELF", "decedent_name": "Not Yet",
         "date_of_death": "2026-09-02", "relationship_to_deceased": "SPOUSE",
         "loss_type": "SUDDEN_DEATH", "contact_name": "Too Early",
         "contact_email": "too.early@example.org"}, RS)
    error = validate_error(resp, ApiErrorId.ERR_DECEASED_DATE_IN_FUTURE.value, 422)
    assert error["error_id"] != ApiErrorId.ERR_INVALID_REQUEST.value
    rows, meta = validate_paginated(api_client.list_referrals(IC))
    assert meta["total_count"] == 0


def test_duplicate_live_referral_is_refused_but_a_declined_one_does_not_block():
    """PRD 3.1: "And the same bereavement must not be filed twice: if a referral
    already exists in status `RECEIVED`, `SCREENED` or `ACCEPTED` carrying the same
    `contact_email` and the same `date_of_death`, the filing is refused with
    `ERR_DUPLICATE_REFERRAL`. A referral that was declined does not block a
    re-file."

    Design: Corner/validations/duplicate_referral_for_same_contact_and_date_of_death_is_refused
    """
    set_clock()
    first = create_referral(
        source_type="HOSPICE", source_org_name="Riverside Hospice",
        decedent_name="Ann Vance", date_of_death="2026-06-01",
        relationship_to_deceased="SPOUSE", loss_type="ANTICIPATED_ILLNESS",
        contact_name="Ben Vance", contact_email="ben.vance@example.org")

    duplicate_payload = {
        "source_type": "FUNERAL_HOME", "source_org_name": "Calder Funeral Home",
        "decedent_name": "Ann Vance", "date_of_death": "2026-06-01",
        "relationship_to_deceased": "SPOUSE", "loss_type": "ANTICIPATED_ILLNESS",
        "contact_name": "Ben Vance", "contact_email": "ben.vance@example.org",
    }
    validate_error(api_client.create_referral(duplicate_payload, RS),
                   ApiErrorId.ERR_DUPLICATE_REFERRAL.value, 409)

    validate_success(
        api_client.decline_referral(first["id"], {"decline_reason": "DUPLICATE"}, IC))
    assert read_referral(first["id"])["status"] == "DECLINED"

    refiled = validate_success(api_client.create_referral(duplicate_payload, RS), 201)
    assert refiled["status"] == "RECEIVED"
    rows, meta = validate_paginated(api_client.list_referrals(IC))
    assert meta["total_count"] == 2, f"Expected 2 referrals on file, got {meta['total_count']}"


def test_screening_an_unknown_referral_is_not_found():
    """PRD 2.5: "Every resource named by a path segment exists, validated from left
    to right, so the leftmost missing segment determines the reported error —
    otherwise the corresponding not-found error (404)."

    Design: Corner/errors/referral_screen_with_unknown_id_returns_referral_not_found
    """
    set_clock()
    validate_error(
        api_client.screen_referral(
            UNUSED_UUIDS["referral"], {"eligibility_note": "n/a"}, IC),
        ApiErrorId.ERR_REFERRAL_NOT_FOUND.value, 404)


def test_logical_clock_reads_the_declared_startup_instant_before_it_is_set():
    """PRD 2.4: "Before an operator ever repositions it, the logical clock reads
    exactly `2026-08-01T00:00:00Z`, and it must never fall back to real wall-clock
    time under any circumstance."

    Design: Corner/endpoints/logical_clock_defaults_to_the_declared_startup_instant
    """
    # Deliberately no clock repositioning: the server must already be at the
    # declared startup instant.
    referral = validate_success(
        api_client.create_referral(
            {"source_type": "SELF", "decedent_name": "Default Clock",
             "date_of_death": "2026-07-02", "relationship_to_deceased": "SPOUSE",
             "loss_type": "SUDDEN_DEATH", "contact_name": "Clock Tester",
             "contact_email": "clock.tester@example.org"}, RS), 201)
    assert referral["created_at"] == "2026-08-01T00:00:00.000Z", (
        f"Expected the declared startup instant, got {referral['created_at']}")

    screened = validate_success(
        api_client.screen_referral(
            referral["id"], {"eligibility_note": "default clock probe"}, IC))
    assert screened["days_since_death"] == 30
    assert screened["screening_band"] == "URGENT"


def test_referral_source_may_not_screen_a_referral():
    """PRD 2.1: "A `ReferralSource` is a hospice team, a funeral-home partner, or a
    self-referring bereaved person, and may do exactly one thing — file an intake
    record."
    PRD 2.1: "When the role named in `X-User-Role` does not appear in the
    authorised-role list of the endpoint being addressed (see §4), the request is
    rejected with `ERR_FORBIDDEN_ROLE` and HTTP 403."

    Design: Corner/rbac/referral_source_cannot_screen_a_referral_returns_forbidden_role
    """
    set_clock()
    referral = create_referral(source_type="SELF", decedent_name="Elin Roos",
                               date_of_death="2026-05-20",
                               relationship_to_deceased="SPOUSE",
                               loss_type="SUDDEN_DEATH", contact_name="Finn Roos",
                               contact_email="finn.roos@example.org")
    validate_error(
        api_client.screen_referral(
            referral["id"], {"eligibility_note": "self screening attempt"}, RS),
        ApiErrorId.ERR_FORBIDDEN_ROLE.value, 403)

    refreshed = read_referral(referral["id"])
    assert refreshed["status"] == "RECEIVED"
    assert refreshed["screening_band"] is None


def test_request_without_the_role_header_is_unauthenticated():
    """PRD 2.1: "If either header is absent, present but empty, or if
    `X-User-Role` carries a value that is not one of the seven declared role names,
    the request is rejected with `ERR_UNAUTHENTICATED` and HTTP 401."

    Design: Corner/rbac/request_missing_x_user_role_header_returns_unauthenticated
    """
    set_clock()
    resp = api_client.create_referral(
        {"source_type": "SELF", "decedent_name": "Elin Roos",
         "date_of_death": "2026-05-20", "relationship_to_deceased": "SPOUSE",
         "loss_type": "SUDDEN_DEATH", "contact_name": "Finn Roos",
         "contact_email": "finn.roos@example.org"},
        headers_without_role("rs-001"))
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)
    rows, meta = validate_paginated(api_client.list_referrals(IC))
    assert meta["total_count"] == 0


def test_single_and_list_reads_share_the_standard_envelope():
    """PRD 2.2: "The `api_request_id` is a server-generated unique identifier for
    the request that starts with `req_`."
    PRD 2.2: "Pagination-related fields in `meta` (`limit`, `offset`,
    `total_count`, `has_more`) are included for list endpoints."

    Design: Corner/endpoints/response_envelope_shape_is_identical_for_object_and_array_reads
    """
    set_clock()
    referral = create_referral(source_type="SELF", decedent_name="Elin Roos",
                               date_of_death="2026-05-20",
                               relationship_to_deceased="SPOUSE",
                               loss_type="SUDDEN_DEATH", contact_name="Finn Roos",
                               contact_email="finn.roos@example.org")

    single = api_client.get_referral(referral["id"], IC)
    body = single.json()
    assert body["response_type"] == "object"
    assert isinstance(body["data"], dict)
    assert body["meta"]["api_request_id"].startswith("req_"), (
        f"api_request_id must start with req_, got {body['meta']['api_request_id']!r}")
    assert validate_success(single)["id"] == referral["id"]

    listed = api_client.list_referrals(IC)
    list_body = listed.json()
    assert list_body["response_type"] == "array"
    assert isinstance(list_body["data"], list)
    rows, meta = validate_paginated(listed)
    assert meta["total_count"] == 1
    assert meta["limit"] == 10 and meta["offset"] == 0
    assert meta["has_more"] is False
    assert rows[0]["id"] == referral["id"]


def test_participant_listing_honours_pagination_defaults_and_filters():
    """PRD 2.3: "`limit` controls page size: it defaults to 10 when omitted, may
    not be smaller than 1, and may not be larger than 100."
    PRD 2.3: "`total_count` reports how many records matched the filter before the
    page window was applied, and `has_more` is true when records remain beyond the
    current window."
    PRD 3.1: "Participants can be listed and filtered by the originating
    `referral_id`, by `service_status`, by `risk_tier` or by `loss_type`."

    Design: Corner/endpoints/participants_list_pagination_honours_limit_and_offset_defaults
    """
    set_clock()
    create_participant(source_type="SELF", decedent_name="D One",
                       date_of_death="2026-06-01", relationship_to_deceased="SPOUSE",
                       loss_type="SUDDEN_DEATH", contact_name="P One",
                       contact_email="p.one@example.org")
    create_participant(source_type="SELF", decedent_name="D Two",
                       date_of_death="2026-06-02", relationship_to_deceased="CHILD",
                       loss_type="SUDDEN_DEATH", contact_name="P Two",
                       contact_email="p.two@example.org")
    third = create_participant(source_type="SELF", decedent_name="D Three",
                               date_of_death="2026-06-03",
                               relationship_to_deceased="SIBLING",
                               loss_type="PERINATAL", contact_name="P Three",
                               contact_email="p.three@example.org")

    rows, meta = validate_paginated(api_client.list_participants(IC))
    assert len(rows) == 3 and meta["total_count"] == 3
    assert meta["limit"] == 10 and meta["offset"] == 0 and meta["has_more"] is False

    rows, meta = validate_paginated(
        api_client.list_participants(IC, params={"limit": 2, "offset": 0}))
    assert len(rows) == 2 and meta["total_count"] == 3
    assert meta["limit"] == 2 and meta["offset"] == 0 and meta["has_more"] is True

    rows, meta = validate_paginated(
        api_client.list_participants(IC, params={"loss_type": "PERINATAL"}))
    assert len(rows) == 1 and rows[0]["id"] == third["id"]


def test_participant_listing_with_limit_above_the_maximum_is_rejected():
    """PRD 2.3: "`limit` controls page size: it defaults to 10 when omitted, may
    not be smaller than 1, and may not be larger than 100."
    PRD 2.3: "A value outside these bounds is a malformed request and is rejected
    under the request-shape rule described in §2.5."

    Design: Corner/endpoints/participants_list_with_limit_above_max_returns_invalid_request
    """
    set_clock()
    validate_error(api_client.list_participants(IC, params={"limit": 101}),
                   ApiErrorId.ERR_INVALID_REQUEST.value, 422)
