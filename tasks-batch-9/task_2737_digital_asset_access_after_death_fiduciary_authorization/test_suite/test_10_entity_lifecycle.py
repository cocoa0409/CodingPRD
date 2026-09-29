"""
Entity lifecycle for the Digital Estate Fiduciary Access API: creation defaults,
single-resource reads, collection paging and filters, path-parameter existence,
body-shape validation, declared defaults, the transferability classification
stamped at creation, the logical-clock stamps and the parent-document linkage of
a request package.

Every test builds all of its own state from the empty database whose logical
clock sits at the fresh-server epoch, so no test depends on any other.
"""

import pytest

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_ASSET_NOT_FOUND,
    ERR_CLAIM_NOT_FOUND,
    ERR_DATE_OF_DEATH_IN_FUTURE,
    ERR_DESIGNATION_NOT_FOUND,
    ERR_DIRECTIVE_NOT_FOUND,
    ERR_DOCUMENT_ESTATE_MISMATCH,
    ERR_DOCUMENT_NOT_FOUND,
    ERR_DOCUMENT_TYPE_MISMATCH,
    ERR_DUPLICATE_ASSET_HANDLE,
    ERR_ELECTION_NOT_FOUND,
    ERR_ESTATE_NOT_FOUND,
    ERR_FIDUCIARY_NOT_FOUND,
    ERR_GRANT_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_ORDER_NOT_FOUND,
    ERR_PLATFORM_NOT_FOUND,
    ERR_REQUEST_NOT_FOUND,
    ERR_SUBSCRIPTION_TERM_NOT_FOUND,
    ERR_VALUATION_RUN_NOT_FOUND,
)
from test_helpers.assertions import (
    assert_common_fields,
    assert_created,
    assert_envelope_array,
    assert_envelope_object,
    assert_fields,
    assert_inventory_counter_identity,
    assert_null_fields,
    assert_page,
)
from test_helpers.constants import (
    ACCESS_CATALOG_DISCLOSED,
    ACCESS_UNVERIFIED,
    APPOINTMENT_EXECUTOR,
    BILLING_NOT_APPLICABLE,
    CATEGORY_CLOUD_STORAGE,
    CATEGORY_EMAIL,
    CATEGORY_FINANCIAL_ACCOUNT,
    CATEGORY_LOYALTY_PROGRAM,
    CATEGORY_SOCIAL_PROFILE,
    CLAIM_FILED,
    CLAMP_NONE,
    CLOCK_EPOCH,
    DEFAULT_LIMIT,
    DEFAULT_OFFSET,
    DISPOSITION_PENDING,
    DOC_ACTION_VERIFY,
    DOC_PENDING,
    DOC_VERIFIED,
    LETTERS_PENDING,
    NON_TRANSFERABLE,
    ORDER_PENDING,
    PHASE_INTAKE,
    PLATFORM_STATUS_LIMITED,
    PLATFORM_STATUS_PARTICIPATING,
    REASON_CATEGORY_PERSONAL,
    REASON_TRANSFERABLE_PROPERTY,
    REFUND_POLICY_NONE,
    REFUND_POLICY_PRORATA_DAILY,
    REQUEST_DRAFT,
    SHARE_BP_TOTAL,
    SOURCE_WILL,
    TRANSFERABLE,
)
from test_helpers.test_users import (
    COURT_REGISTRAR_HEADERS,
    COURT_REGISTRAR_USER_ID,
    ESTATE_ADMIN_HEADERS,
    make_fiduciary_headers,
    make_platform_compliance_headers,
)


# ─── Local helpers ───────────────────────────────────────────────────────────
def _instant(value):
    """Render an ISO 8601 UTC instant with three fractional digits for comparison."""
    assert isinstance(value, str) and value.endswith("Z"), (
        f"Expected an ISO 8601 UTC instant ending in Z, got {value!r}"
    )
    head = value[:-1]
    if "." not in head:
        return head + ".000Z"
    stem, frac = head.split(".", 1)
    return f"{stem}.{(frac + '000')[:3]}Z"


def _estate_with_fiduciary(api, case_number, **estate_overrides):
    """Open an estate and appoint one fiduciary; no paperwork is verified."""
    estate = fx.open_estate(api, court_case_number=case_number, **estate_overrides)
    fiduciary = fx.appoint_fiduciary(
        api, estate["id"], court_reference=f"APPT-{case_number}"
    )
    return estate, fiduciary, make_fiduciary_headers(fiduciary["id"])


# ─── Opening the estate file ─────────────────────────────────────────────────
def test_new_estate_opens_in_intake_with_every_counter_and_mirror_at_zero(api):
    """A freshly opened estate reports INTAKE, all-zero counters and money mirrors, and null valuation and closure fields.

    The new estate opens with `administration_phase` set to `INTAKE`, every counter at 0, every money mirror at 0, `valuation_basis` null, and `closing_statement` and `closed_at` both null.

    Design: Corner/entities/estate_creation_returns_intake_phase_zeroed_counters_and_the_alternate_date
    """
    fx.set_clock(api, CLOCK_EPOCH)

    response = api.create_estate(
        f.estate_payload(
            decedent_name="Rowan Ives",
            date_of_death="2026-02-14",
            domicile_state="CA",
            court_case_number="PR-2737-C01",
        ),
        ESTATE_ADMIN_HEADERS,
    )

    estate = assert_created(response)
    assert_envelope_object(response)
    assert_fields(
        estate,
        administration_phase=PHASE_INTAKE,
        inventory_total_count=0,
        disclosed_asset_count=0,
        assets_pending_disposition_count=0,
        assets_disposed_count=0,
        open_cancellation_count=0,
        cancelled_subscription_count=0,
        gross_digital_estate_cents=0,
        admin_deduction_cents=0,
        taxable_digital_estate_cents=0,
        undistributed_value_cents=0,
        refund_recovered_cents=0,
    )
    assert_null_fields(estate, "valuation_basis", "closing_statement", "closed_at")
    assert_inventory_counter_identity(estate)
    assert_common_fields(estate, expected_version=1)
    assert _instant(estate["created_at"]) == "2026-08-01T00:00:00.000Z"
    assert _instant(estate["updated_at"]) == _instant(estate["created_at"])


def test_alternate_valuation_date_is_death_plus_six_calendar_months(api):
    """The alternate valuation date is computed at creation as the date of death plus six calendar months, clamped to the last day of a shorter target month.

    On creation the server computes `alternate_valuation_date` as the date of death advanced by exactly six calendar months, using the last-day-of-month clamp described in §2.5; this date gates the alternate valuation basis and is never client-supplied.

    Design: Corner/entities/estate_creation_returns_intake_phase_zeroed_counters_and_the_alternate_date
    """
    fx.set_clock(api, CLOCK_EPOCH)

    mid_month = fx.open_estate(
        api, date_of_death="2026-02-14", court_case_number="PR-2737-C01A"
    )
    assert mid_month["alternate_valuation_date"] == "2026-08-14"

    clamped = fx.open_estate(
        api, date_of_death="2025-08-31", court_case_number="PR-2737-C01B"
    )
    assert clamped["alternate_valuation_date"] == "2026-02-28"


def test_date_of_death_may_equal_today_but_never_lie_in_the_future(api):
    """A date of death equal to the clock's calendar date is accepted while a later one is refused.

    The date of death may not be later than the logical clock's current calendar date; a date equal to today is accepted, while a date in the future is rejected with `ERR_DATE_OF_DEATH_IN_FUTURE`.

    Design: Corner/entities/estate_creation_returns_intake_phase_zeroed_counters_and_the_alternate_date
    """
    fx.set_clock(api, CLOCK_EPOCH)

    future = api.create_estate(
        f.estate_payload(
            date_of_death="2026-08-31", court_case_number="PR-2737-C01C"
        ),
        ESTATE_ADMIN_HEADERS,
    )
    validate_error(future, ERR_DATE_OF_DEATH_IN_FUTURE)

    today = api.create_estate(
        f.estate_payload(
            date_of_death="2026-08-01", court_case_number="PR-2737-C01D"
        ),
        ESTATE_ADMIN_HEADERS,
    )
    accepted = validate_success(today, 201)
    assert_fields(
        accepted,
        date_of_death="2026-08-01",
        alternate_valuation_date="2027-02-01",
        administration_phase=PHASE_INTAKE,
    )


# ─── Single-resource reads ───────────────────────────────────────────────────
def test_platform_single_read_echoes_the_stored_policy_to_all_four_roles(api):
    """Reading one provider back returns its whole death-administration policy unchanged, and every role may perform the read.

    All read endpoints are open to all four roles with five exceptions, all of which exclude `PlatformCompliance`: the estate collection listing, the authority-directive listings and single reads, the beneficiary-designation listings and single reads, the valuation-run listings and single reads, and the authority-resolution projection.

    Design: Corner/entities/single_resource_reads_return_every_stored_and_derived_field
    """
    fx.set_clock(api, CLOCK_EPOCH)
    platform = fx.register_platform(api, transfer_fee_cents=2500, request_fee_cents=1500)
    _, _, fid_headers = _estate_with_fiduciary(api, "PR-2737-C02")

    response = api.get_platform(platform["id"], fid_headers)
    stored = validate_success(response, 200)
    assert_envelope_object(response)
    assert_fields(
        stored,
        id=platform["id"],
        name="CloudVault",
        platform_type="CLOUD_STORAGE",
        form_code="CV-FORM-1",
        review_window_days=14,
        refund_policy=REFUND_POLICY_NONE,
        status=PLATFORM_STATUS_PARTICIPATING,
        supports_online_tool=True,
        supports_transfer=True,
        supports_memorialization=True,
        supports_deletion=True,
        requires_court_order_for_content=False,
        license_terminates_at_death=False,
        transfer_fee_cents=2500,
        request_fee_cents=1500,
    )
    assert_common_fields(stored, expected_version=1)

    for headers in (
        ESTATE_ADMIN_HEADERS,
        COURT_REGISTRAR_HEADERS,
        fid_headers,
        make_platform_compliance_headers(platform["id"]),
    ):
        again = validate_success(api.get_platform(platform["id"], headers), 200)
        assert again["version"] == 1, "A read must not mutate the record it reads"


def test_freshly_appointed_fiduciary_reads_back_with_pending_letters(api):
    """An appointment on its own leaves the fiduciary's letters pending.

    An appointment confers nothing on its own: `letters_status` starts at `PENDING` and stays there until paperwork proves otherwise.

    Design: Corner/entities/single_resource_reads_return_every_stored_and_derived_field
    """
    fx.set_clock(api, CLOCK_EPOCH)
    platform = fx.register_platform(api)
    estate, fiduciary, _ = _estate_with_fiduciary(api, "PR-2737-C02B")

    response = api.get_fiduciary(
        fiduciary["id"], make_platform_compliance_headers(platform["id"])
    )
    stored = validate_success(response, 200)
    assert_envelope_object(response)
    assert_fields(
        stored,
        id=fiduciary["id"],
        estate_id=estate["id"],
        full_name="Dana Ives",
        appointment_type=APPOINTMENT_EXECUTOR,
        court_reference="APPT-PR-2737-C02B",
        letters_status=LETTERS_PENDING,
    )
    assert_common_fields(stored, expected_version=1)


def test_estate_read_still_reports_intake_before_any_paperwork_is_verified(api):
    """An estate that has a fiduciary but no verified death certificate and no issued letters still reads INTAKE.

    Otherwise, if the estate has no `DEATH_CERTIFICATE` document in `VERIFIED` status, or no fiduciary at all with `letters_status` equal to `ISSUED`, the phase is `INTAKE`.

    Design: Corner/entities/single_resource_reads_return_every_stored_and_derived_field
    """
    fx.set_clock(api, CLOCK_EPOCH)
    estate, _, _ = _estate_with_fiduciary(api, "PR-2737-C02C")

    response = api.get_estate(estate["id"], COURT_REGISTRAR_HEADERS)
    stored = validate_success(response, 200)
    assert_envelope_object(response)
    assert_fields(
        stored,
        id=estate["id"],
        administration_phase=PHASE_INTAKE,
        court_case_number="PR-2737-C02C",
        domicile_state="CA",
    )


# ─── Collection paging and filters ───────────────────────────────────────────
def _three_asset_estate(api, case_number):
    """Three accounts on one estate, each created at a distinct clock instant."""
    fx.set_clock(api, CLOCK_EPOCH)
    platform = fx.register_platform(api)
    estate, _, fid_headers = _estate_with_fiduciary(api, case_number)

    def _add(handle, category, cents):
        return validate_success(
            api.create_digital_asset(
                estate["id"],
                f.digital_asset_payload(
                    platform["id"],
                    category=category,
                    account_handle=handle,
                    quoted_value_cents=cents,
                ),
                fid_headers,
            ),
            201,
        )

    first = _add("vault-a", CATEGORY_CLOUD_STORAGE, 10000)
    fx.set_clock(api, "2026-08-01T00:01:00Z")
    second = _add("vault-b", CATEGORY_CLOUD_STORAGE, 20000)
    fx.set_clock(api, "2026-08-01T00:02:00Z")
    third = _add("inbox-a", CATEGORY_EMAIL, 0)
    return estate, fid_headers, [first, second, third]


def test_digital_asset_pages_carry_the_four_meta_fields_oldest_first(api):
    """Paging a three-account inventory two at a time reports the filtered total, the page window and whether more records remain.

    For a list response, the `meta` object carries the four pagination fields `limit` (the effective page size actually applied), `offset` (the effective offset actually applied), `total_count` (the number of records matching the filters before pagination) and `has_more` (true when records remain beyond this page).

    Design: Corner/entities/digital_asset_list_filters_by_access_status_and_paginates_with_total_count
    """
    estate, fid_headers, assets = _three_asset_estate(api, "PR-2737-C03")

    page_one = api.list_digital_assets(
        fid_headers, estate_id=estate["id"], limit=2, offset=0
    )
    assert_envelope_array(page_one)
    assert_page(
        page_one,
        expected_ids=[assets[0]["id"], assets[1]["id"]],
        total_count=3,
        has_more=True,
        limit=2,
        offset=0,
    )

    page_two = api.list_digital_assets(
        fid_headers, estate_id=estate["id"], limit=2, offset=2
    )
    assert_page(
        page_two,
        expected_ids=[assets[2]["id"]],
        total_count=3,
        has_more=False,
        limit=2,
        offset=2,
    )


def test_digital_asset_filters_report_the_filtered_cardinality(api):
    """A category filter narrows the rows and the total, and a filter that matches nothing returns an empty page.

    Digital assets may be filtered by `estate_id`, `platform_id`, `category`, `access_status`, `disposition_status` and `transferability`.

    Design: Corner/entities/digital_asset_list_filters_by_access_status_and_paginates_with_total_count
    """
    estate, fid_headers, assets = _three_asset_estate(api, "PR-2737-C03B")

    email_only = api.list_digital_assets(
        fid_headers, estate_id=estate["id"], category=CATEGORY_EMAIL
    )
    assert_page(email_only, expected_ids=[assets[2]["id"]], total_count=1, has_more=False)

    unverified = api.list_digital_assets(
        fid_headers, estate_id=estate["id"], access_status=ACCESS_UNVERIFIED
    )
    assert_page(
        unverified,
        expected_ids=[assets[0]["id"], assets[1]["id"], assets[2]["id"]],
        total_count=3,
        has_more=False,
    )

    disclosed = api.list_digital_assets(
        fid_headers, estate_id=estate["id"], access_status=ACCESS_CATALOG_DISCLOSED
    )
    assert_page(disclosed, expected_ids=[], total_count=0, has_more=False)


def test_digital_asset_listing_defaults_to_limit_ten_offset_zero(api):
    """Omitting both pagination parameters applies the declared defaults and returns every unfiltered row.

    `limit` controls how many records are returned; it defaults to 10 when omitted, may not be smaller than 1, and may not be larger than 100.

    Design: Corner/entities/digital_asset_list_filters_by_access_status_and_paginates_with_total_count
    """
    _, fid_headers, assets = _three_asset_estate(api, "PR-2737-C03C")

    unpaged = api.list_digital_assets(fid_headers)
    assert_page(
        unpaged,
        expected_ids=[assets[0]["id"], assets[1]["id"], assets[2]["id"]],
        total_count=3,
        has_more=False,
        limit=DEFAULT_LIMIT,
        offset=DEFAULT_OFFSET,
    )


# ─── Path-parameter existence ────────────────────────────────────────────────
_NOT_FOUND_CASES = [
    ("/estates", ERR_ESTATE_NOT_FOUND),
    ("/fiduciaries", ERR_FIDUCIARY_NOT_FOUND),
    ("/documents", ERR_DOCUMENT_NOT_FOUND),
    ("/platforms", ERR_PLATFORM_NOT_FOUND),
    ("/authority-directives", ERR_DIRECTIVE_NOT_FOUND),
    ("/digital-assets", ERR_ASSET_NOT_FOUND),
    ("/subscription-terms", ERR_SUBSCRIPTION_TERM_NOT_FOUND),
    ("/platform-requests", ERR_REQUEST_NOT_FOUND),
    ("/authority-grants", ERR_GRANT_NOT_FOUND),
    ("/beneficiary-designations", ERR_DESIGNATION_NOT_FOUND),
    ("/disposition-elections", ERR_ELECTION_NOT_FOUND),
    ("/cancellation-orders", ERR_ORDER_NOT_FOUND),
    ("/refund-claims", ERR_CLAIM_NOT_FOUND),
    ("/valuation-runs", ERR_VALUATION_RUN_NOT_FOUND),
]


@pytest.mark.parametrize(
    "collection,expected_error",
    _NOT_FOUND_CASES,
    ids=[case[0].strip("/") for case in _NOT_FOUND_CASES],
)
def test_each_path_parameter_raises_its_own_not_found_error(api, collection, expected_error):
    """Every one of the fourteen path parameters answers an unknown identifier with the error identifier reserved for its own entity.

    **Path-parameter existence**, in the fixed sequence estate, fiduciary, document, platform, directive, asset, subscription term, platform request, authority grant, beneficiary designation, disposition election, cancellation order, refund claim, valuation run — raising respectively `ERR_ESTATE_NOT_FOUND`, `ERR_FIDUCIARY_NOT_FOUND`, `ERR_DOCUMENT_NOT_FOUND`, `ERR_PLATFORM_NOT_FOUND`, `ERR_DIRECTIVE_NOT_FOUND`, `ERR_ASSET_NOT_FOUND`, `ERR_SUBSCRIPTION_TERM_NOT_FOUND`, `ERR_REQUEST_NOT_FOUND`, `ERR_GRANT_NOT_FOUND`, `ERR_DESIGNATION_NOT_FOUND`, `ERR_ELECTION_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND` and `ERR_VALUATION_RUN_NOT_FOUND`, all HTTP 404.

    Design: Corner/entities/every_path_parameter_rejects_an_unknown_id_with_its_own_not_found_error
    """
    fx.set_clock(api, CLOCK_EPOCH)

    response = api.raw(
        "GET", f"{collection}/{NON_EXISTENT_UUID}", None, ESTATE_ADMIN_HEADERS
    )

    body = validate_error(response, expected_error)
    assert response.json()["response_type"] == "error"
    assert body["message"].strip(), "An error envelope carries a human-readable message"


def test_unknown_estate_in_the_path_fails_before_the_body_is_examined(api):
    """A creation call that names a non-existent estate fails on the path parameter even though its body is perfectly valid.

    A request naming a non-existent estate fails with `ERR_ESTATE_NOT_FOUND` before anything in the body is looked at; a request naming a real order but a non-existent claim fails on the claim.

    Design: Corner/entities/every_path_parameter_rejects_an_unknown_id_with_its_own_not_found_error
    """
    fx.set_clock(api, CLOCK_EPOCH)
    platform = fx.register_platform(api)
    _, _, fid_headers = _estate_with_fiduciary(api, "PR-2737-C04A")

    response = api.create_digital_asset(
        NON_EXISTENT_UUID,
        f.digital_asset_payload(platform["id"], account_handle="vault-a"),
        fid_headers,
    )

    validate_error(response, ERR_ESTATE_NOT_FOUND)


# ─── Body shape: required fields, enums and ranges ───────────────────────────
_BAD_ASSET_BODIES = [
    ("missing_platform_id", {"platform_id": None}),
    ("missing_category", {"category": None}),
    ("missing_account_handle", {"account_handle": None}),
    ("missing_quoted_value_cents", {"quoted_value_cents": None}),
    ("category_outside_the_enum", {"category": "PHOTO_ALBUM"}),
    ("negative_quoted_value_cents", {"quoted_value_cents": -1}),
    ("negative_loyalty_points", {"loyalty_points": -5}),
]


@pytest.mark.parametrize(
    "case,overrides",
    _BAD_ASSET_BODIES,
    ids=[case[0] for case in _BAD_ASSET_BODIES],
)
def test_malformed_asset_body_is_rejected_and_persists_nothing(api, case, overrides):
    """A missing required field, a category outside the enum or a negative cents value all fail body validation with one code, and the inventory is left untouched.

    **Authentication and request shape.** Header presence (`ERR_MISSING_AUTH_HEADERS`, 401); role recognisability (`ERR_UNKNOWN_ROLE`, 401); endpoint-level role permission (`ERR_ROLE_NOT_PERMITTED`, 403); body well-formedness on every write endpoint — parseable JSON, every required field present, no unknown field that would change behaviour, and every field matching its declared type, enum membership and range, including `share_bp` between 1 and 10000 inclusive, cents fields being non-negative integers, and dates and datetimes being valid ISO 8601 (`ERR_INVALID_REQUEST`, 400); and finally action-level role ownership on every transitions endpoint (`ERR_ACTION_ROLE_MISMATCH`, 403).

    Design: Corner/entities/missing_required_inputs_and_out_of_range_values_return_invalid_request
    """
    fx.set_clock(api, CLOCK_EPOCH)
    platform = fx.register_platform(api)
    estate, _, fid_headers = _estate_with_fiduciary(api, "PR-2737-C04")

    good = api.create_digital_asset(
        estate["id"],
        f.digital_asset_payload(
            platform["id"], account_handle="vault-a", quoted_value_cents=10000
        ),
        fid_headers,
    )
    validate_success(good, 201)
    after_good = validate_success(api.get_estate(estate["id"], fid_headers), 200)
    assert after_good["inventory_total_count"] == 1

    bad_payload = f.digital_asset_payload(
        platform["id"], account_handle="vault-b", quoted_value_cents=10000
    )
    # A None override drops the key entirely, mirroring the factory's own merge
    # semantics; this cannot go through the factory because ``platform_id`` is
    # one of the keys under test and is also the factory's positional argument.
    for key, value in overrides.items():
        if value is None:
            bad_payload.pop(key, None)
        else:
            bad_payload[key] = value
    bad = api.create_digital_asset(estate["id"], bad_payload, fid_headers)
    validate_error(bad, ERR_INVALID_REQUEST)

    after_bad = validate_success(api.get_estate(estate["id"], fid_headers), 200)
    assert after_bad["inventory_total_count"] == 1, (
        "A rejected creation must not reach the inventory"
    )
    rows, meta = assert_envelope_array(
        api.list_digital_assets(fid_headers, estate_id=estate["id"])
    )
    assert meta["total_count"] == 1 and len(rows) == 1


def test_review_window_days_outside_one_to_ninety_is_rejected(api):
    """A provider's review window must be a whole number of days between one and ninety inclusive.

    `review_window_days` is the length, in whole days, of the review window that a submitted request occupies with this provider, and must be at least 1 and at most 90.

    Design: Corner/entities/missing_required_inputs_and_out_of_range_values_return_invalid_request
    """
    fx.set_clock(api, CLOCK_EPOCH)

    for bad_value in (0, 91):
        response = api.create_platform(
            f.platform_payload(review_window_days=bad_value, form_code="CV-BAD"),
            ESTATE_ADMIN_HEADERS,
        )
        validate_error(response, ERR_INVALID_REQUEST)

    for good_value in (1, 90):
        response = api.create_platform(
            f.platform_payload(
                review_window_days=good_value, form_code=f"CV-OK-{good_value}"
            ),
            ESTATE_ADMIN_HEADERS,
        )
        accepted = validate_success(response, 201)
        assert accepted["review_window_days"] == good_value


def test_domicile_state_must_be_exactly_two_uppercase_letters(api):
    """The estate's domicile is a two-letter uppercase jurisdiction code, so a three-letter or lowercase value fails validation.

    The **`Estate`** is created from four supplied values: `decedent_name` (non-empty, at most 200 characters), `date_of_death`, `domicile_state` (exactly two uppercase letters, naming the jurisdiction whose default statutory rules apply), and `court_case_number` (non-empty, at most 60 characters, the probate identifier printed on the letters of authority).

    Design: Corner/entities/missing_required_inputs_and_out_of_range_values_return_invalid_request
    """
    fx.set_clock(api, CLOCK_EPOCH)

    for bad_state in ("Cal", "ca"):
        response = api.create_estate(
            f.estate_payload(
                domicile_state=bad_state, court_case_number=f"PR-2737-C04-{bad_state}"
            ),
            ESTATE_ADMIN_HEADERS,
        )
        validate_error(response, ERR_INVALID_REQUEST)


def test_share_bp_outside_one_to_ten_thousand_is_rejected(api):
    """A beneficiary's basis-point share must lie between one and ten thousand inclusive.

    An individual share must be between 1 and 10000 inclusive, and the shares recorded against one estate must sum to exactly 10000 before the estate can be valued.

    Design: Corner/entities/missing_required_inputs_and_out_of_range_values_return_invalid_request
    """
    fx.set_clock(api, CLOCK_EPOCH)
    estate, _, fid_headers = _estate_with_fiduciary(api, "PR-2737-C04B")

    for bad_share in (0, 10001):
        response = api.create_beneficiary_designation(
            estate["id"], f.beneficiary_payload(share_bp=bad_share), fid_headers
        )
        validate_error(response, ERR_INVALID_REQUEST)

    accepted = validate_success(
        api.create_beneficiary_designation(
            estate["id"],
            f.beneficiary_payload(share_bp=SHARE_BP_TOTAL, source=SOURCE_WILL),
            fid_headers,
        ),
        201,
    )
    assert accepted["share_bp"] == SHARE_BP_TOTAL


def test_document_filing_rejects_an_expected_version_field(api):
    """Document filing takes no optimistic-concurrency token, so supplying one is an unknown field.

    In particular, transitions endpoints, provider policy updates, document filing and closure carry no expected-version input, and supplying one is an unknown field that fails body validation.

    Design: Corner/entities/missing_required_inputs_and_out_of_range_values_return_invalid_request
    """
    fx.set_clock(api, CLOCK_EPOCH)
    estate, _, _ = _estate_with_fiduciary(api, "PR-2737-C04C")

    response = api.create_document(
        estate["id"],
        f.document_payload(reference_number="DC-C04C", expected_estate_version=1),
        COURT_REGISTRAR_HEADERS,
    )

    validate_error(response, ERR_INVALID_REQUEST)


# ─── Declared defaults for omitted optional inputs ───────────────────────────
def test_platform_status_defaults_to_participating_but_honours_an_explicit_value(api):
    """A provider registered without a status posture opens PARTICIPATING, while an explicit LIMITED is stored as given.

    Its operational posture is the `status` field, one of `PARTICIPATING`, `LIMITED` or `SUSPENDED`; `status` may be supplied at registration and defaults to `PARTICIPATING` when omitted.

    Design: Corner/entities/omitted_optional_inputs_fall_back_to_their_declared_defaults
    """
    fx.set_clock(api, CLOCK_EPOCH)

    defaulted = validate_success(
        api.create_platform(
            f.loyalty_platform_payload(name="LoyalMiles", form_code="LM-FORM-2"),
            ESTATE_ADMIN_HEADERS,
        ),
        201,
    )
    assert defaulted["status"] == PLATFORM_STATUS_PARTICIPATING

    explicit = validate_success(
        api.create_platform(
            f.loyalty_platform_payload(
                name="LoyalMiles Two",
                form_code="LM-FORM-3",
                status=PLATFORM_STATUS_LIMITED,
            ),
            ESTATE_ADMIN_HEADERS,
        ),
        201,
    )
    assert explicit["status"] == PLATFORM_STATUS_LIMITED


def test_newly_inventoried_account_opens_undisclosed_and_undisposed(api):
    """A just-inventoried loyalty account opens UNVERIFIED with no clamp, PENDING disposition, no billing state and every stamp and appraisal still null.

    A newly inventoried account opens at `access_status` `UNVERIFIED`, `content_clamp_reason` `NONE`, and `disposition_status` `PENDING`, with `disclosed_at`, `disposed_at`, `appraised_value_cents` and `appraised_basis` all null. Its `subscription_billing_state` opens at `ACTIVE` when its `category` is `SUBSCRIPTION` and at `NOT_APPLICABLE` for every other category.

    Design: Corner/entities/omitted_optional_inputs_fall_back_to_their_declared_defaults
    """
    fx.set_clock(api, CLOCK_EPOCH)
    platform = fx.register_loyalty_platform(api, name="LoyalMiles", form_code="LM-FORM-2")
    estate, _, fid_headers = _estate_with_fiduciary(api, "PR-2737-C05")

    asset = validate_success(
        api.create_digital_asset(
            estate["id"],
            f.digital_asset_payload(
                platform["id"],
                category=CATEGORY_LOYALTY_PROGRAM,
                account_handle="miles-1",
                quoted_value_cents=30000,
            ),
            fid_headers,
        ),
        201,
    )

    assert_fields(
        asset,
        access_status=ACCESS_UNVERIFIED,
        content_clamp_reason=CLAMP_NONE,
        disposition_status=DISPOSITION_PENDING,
        subscription_billing_state=BILLING_NOT_APPLICABLE,
    )
    assert_null_fields(
        asset, "disclosed_at", "disposed_at", "appraised_value_cents", "appraised_basis"
    )


def test_loyalty_points_default_to_zero_when_omitted(api):
    """Omitting the audit-only points balance records 0 rather than null, while a supplied balance is kept verbatim.

    The fiduciary also supplies `quoted_value_cents`, the provider's own date-of-death value quote for the account as a non-negative integer, and may optionally supply `loyalty_points` (a non-negative integer that defaults to 0 and is recorded purely for audit — it enters no formula anywhere in this specification) and a free-text `inventory_note`.

    Design: Corner/entities/omitted_optional_inputs_fall_back_to_their_declared_defaults
    """
    fx.set_clock(api, CLOCK_EPOCH)
    platform = fx.register_loyalty_platform(api, name="LoyalMiles", form_code="LM-FORM-2")
    estate, _, fid_headers = _estate_with_fiduciary(api, "PR-2737-C05B")

    defaulted = validate_success(
        api.create_digital_asset(
            estate["id"],
            f.digital_asset_payload(
                platform["id"],
                category=CATEGORY_LOYALTY_PROGRAM,
                account_handle="miles-1",
                quoted_value_cents=30000,
            ),
            fid_headers,
        ),
        201,
    )
    assert defaulted["loyalty_points"] == 0
    assert isinstance(defaulted["loyalty_points"], int)

    supplied = validate_success(
        api.create_digital_asset(
            estate["id"],
            f.digital_asset_payload(
                platform["id"],
                category=CATEGORY_LOYALTY_PROGRAM,
                account_handle="miles-2",
                quoted_value_cents=30000,
                loyalty_points=45000,
            ),
            fid_headers,
        ),
        201,
    )
    assert supplied["loyalty_points"] == 45000


def test_designation_ranks_are_dense_and_open_with_zero_money(api):
    """Each designation is ranked one past the designations already on file and starts with nothing planned and nothing received.

    The server assigns `allocation_rank` as one more than the number of designations the estate already has, so ranks are dense, 1-based and follow `created_at` ascending order, and it opens `planned_allocation_cents` and `received_value_cents` at 0.

    Design: Corner/entities/omitted_optional_inputs_fall_back_to_their_declared_defaults
    """
    fx.set_clock(api, CLOCK_EPOCH)
    estate, _, fid_headers = _estate_with_fiduciary(api, "PR-2737-C05C")

    first = validate_success(
        api.create_beneficiary_designation(
            estate["id"],
            f.beneficiary_payload(
                beneficiary_name="Ada Ives", share_bp=5000, source=SOURCE_WILL
            ),
            fid_headers,
        ),
        201,
    )
    assert_fields(
        first,
        allocation_rank=1,
        planned_allocation_cents=0,
        received_value_cents=0,
    )

    second = validate_success(
        api.create_beneficiary_designation(
            estate["id"],
            f.beneficiary_payload(
                beneficiary_name="Bram Ives", share_bp=5000, source=SOURCE_WILL
            ),
            fid_headers,
        ),
        201,
    )
    assert_fields(
        second,
        allocation_rank=2,
        planned_allocation_cents=0,
        received_value_cents=0,
    )


def test_auto_created_cancellation_order_opens_pending_with_the_policy_snapshot(api):
    """The order a first disclosure creates for a subscription account opens PENDING with the provider's refund policy already copied onto it.

    The third hop looks after recurring charges. For every account the second hop has just disclosed whose `category` is `SUBSCRIPTION` and which does not already have a cancellation order, the system creates a **`CancellationOrder`** in `PENDING` status and copies the provider's `refund_policy` into the order's `refund_policy_snapshot` at that moment.

    Design: Corner/entities/omitted_optional_inputs_fall_back_to_their_declared_defaults
    """
    fx.set_clock(api, CLOCK_EPOCH)
    platform = fx.register_subscription_platform(api)
    assert platform["refund_policy"] == REFUND_POLICY_PRORATA_DAILY
    ctx = fx.authorized_estate(api, "PR-2737-C05D")
    asset = fx.add_subscription_asset(api, ctx, platform["id"])
    fx.add_subscription_term(api, ctx, asset["id"])

    fx.approved_request(api, ctx, platform["id"], platform["form_code"])

    order = fx.cancellation_order_for_asset(api, ctx, asset["id"])
    reread = validate_success(api.get_cancellation_order(order["id"], ctx.fid_headers), 200)
    assert_fields(
        reread,
        status=ORDER_PENDING,
        asset_id=asset["id"],
        refund_policy_snapshot=REFUND_POLICY_PRORATA_DAILY,
    )


def test_new_refund_claim_opens_filed_with_nothing_credited(api):
    """A freshly filed claim starts FILED with no credit yet, and its ten claimed days land on the term's running total.

    A new claim opens with `status` at `FILED` and `credited_cents` at 0, and the term's `claimed_days_total` — defined as the sum of `claimed_days` across the claims on that term in `FILED`, `PLATFORM_REVIEW`, `ESCALATED` or `CREDITED` — rises by this claim's `claimed_days`.

    Design: Corner/entities/omitted_optional_inputs_fall_back_to_their_declared_defaults
    """
    fx.set_clock(api, CLOCK_EPOCH)
    platform = fx.register_subscription_platform(api)
    ctx = fx.authorized_estate(api, "PR-2737-C05E")
    runway = fx.subscription_with_confirmed_order(api, ctx, platform)
    term_id = runway["term"]["id"]
    assert (
        validate_success(api.get_subscription_term(term_id, ctx.fid_headers), 200)[
            "claimed_days_total"
        ]
        == 0
    )

    claim = validate_success(
        api.create_refund_claim(
            runway["order"]["id"],
            f.refund_claim_payload("2026-04-01", "2026-04-10"),
            ctx.fid_headers,
        ),
        201,
    )

    assert_fields(claim, status=CLAIM_FILED, credited_cents=0, claimed_days=10)
    term = validate_success(api.get_subscription_term(term_id, ctx.fid_headers), 200)
    assert term["claimed_days_total"] == 10


# ─── Transferability stamped at creation ─────────────────────────────────────
def _open_platform_estate(api, case_number):
    """A provider that permits transfers and whose licence survives death, plus a bare estate."""
    platform = fx.register_social_platform(
        api,
        name="OpenNet",
        form_code="ON-FORM-3",
        supports_online_tool=True,
        supports_transfer=True,
    )
    assert platform["supports_transfer"] is True
    assert platform["license_terminates_at_death"] is False
    estate, _, fid_headers = _estate_with_fiduciary(api, case_number)
    return platform, estate, fid_headers


@pytest.mark.parametrize(
    "category,handle",
    [(CATEGORY_EMAIL, "inbox-1"), (CATEGORY_SOCIAL_PROFILE, "profile-1")],
    ids=["email", "social_profile"],
)
def test_personal_categories_are_non_transferable_even_where_transfers_are_allowed(
    api, category, handle
):
    """Mailboxes and social profiles are personal to the decedent, so they classify as non-transferable no matter how permissive the provider is.

    Rule one: an account whose `category` is `EMAIL` or `SOCIAL_PROFILE` is `NON_TRANSFERABLE` with reason `CATEGORY_PERSONAL` — these are personal to the decedent and cannot be handed to anyone.

    Design: Corner/entities/transferability_is_computed_at_creation_for_the_personal_and_default_rules
    """
    fx.set_clock(api, CLOCK_EPOCH)
    platform, estate, fid_headers = _open_platform_estate(api, "PR-2737-C06")

    asset = validate_success(
        api.create_digital_asset(
            estate["id"],
            f.digital_asset_payload(
                platform["id"],
                category=category,
                account_handle=handle,
                quoted_value_cents=0,
            ),
            fid_headers,
        ),
        201,
    )

    assert_fields(
        asset,
        category=category,
        transferability=NON_TRANSFERABLE,
        transferability_reason=REASON_CATEGORY_PERSONAL,
    )


@pytest.mark.parametrize(
    "category,handle,quoted",
    [
        (CATEGORY_CLOUD_STORAGE, "vault-1", 400033),
        (CATEGORY_FINANCIAL_ACCOUNT, "acct-1", 250000),
    ],
    ids=["cloud_storage", "financial_account"],
)
def test_accounts_matching_no_earlier_rule_fall_through_to_transferable_property(
    api, category, handle, quoted
):
    """A vault and a financial account on that same permissive provider match none of the first five rules, so they end up transferable property.

    Rule six, reached only when nothing above matched: the account is `TRANSFERABLE` with reason `TRANSFERABLE_PROPERTY`.

    Design: Corner/entities/transferability_is_computed_at_creation_for_the_personal_and_default_rules
    """
    fx.set_clock(api, CLOCK_EPOCH)
    platform, estate, fid_headers = _open_platform_estate(api, "PR-2737-C06B")

    asset = validate_success(
        api.create_digital_asset(
            estate["id"],
            f.digital_asset_payload(
                platform["id"],
                category=category,
                account_handle=handle,
                quoted_value_cents=quoted,
            ),
            fid_headers,
        ),
        201,
    )

    assert_fields(
        asset,
        category=category,
        transferability=TRANSFERABLE,
        transferability_reason=REASON_TRANSFERABLE_PROPERTY,
    )
    assert asset["quoted_value_cents"] == quoted


def test_each_added_account_lifts_the_inventory_and_pending_counters(api):
    """Four inventoried accounts leave the estate counting four in total and four still awaiting disposition.

    Adding an account increments the estate's `inventory_total_count` and `assets_pending_disposition_count` and re-derives the `administration_phase`.

    Design: Corner/entities/transferability_is_computed_at_creation_for_the_personal_and_default_rules
    """
    fx.set_clock(api, CLOCK_EPOCH)
    platform, estate, fid_headers = _open_platform_estate(api, "PR-2737-C06C")

    for category, handle, quoted in (
        (CATEGORY_EMAIL, "inbox-1", 0),
        (CATEGORY_SOCIAL_PROFILE, "profile-1", 0),
        (CATEGORY_CLOUD_STORAGE, "vault-1", 400033),
        (CATEGORY_FINANCIAL_ACCOUNT, "acct-1", 250000),
    ):
        validate_success(
            api.create_digital_asset(
                estate["id"],
                f.digital_asset_payload(
                    platform["id"],
                    category=category,
                    account_handle=handle,
                    quoted_value_cents=quoted,
                ),
                fid_headers,
            ),
            201,
        )

    reread = validate_success(api.get_estate(estate["id"], fid_headers), 200)
    assert_fields(
        reread, inventory_total_count=4, assets_pending_disposition_count=4
    )
    assert_inventory_counter_identity(reread)


def test_handle_uniqueness_is_scoped_to_one_provider(api):
    """Re-using a handle on the same provider collides, while the same handle on a different provider is a different account.

    The handle must be unique within the estate for that provider: a second account with the same combination of `platform_id` and `account_handle` on the same estate is rejected with `ERR_DUPLICATE_ASSET_HANDLE`, while two different estates may perfectly well list the same handle.

    Design: Corner/entities/transferability_is_computed_at_creation_for_the_personal_and_default_rules
    """
    fx.set_clock(api, CLOCK_EPOCH)
    platform, estate, fid_headers = _open_platform_estate(api, "PR-2737-C06D")
    other_platform = fx.register_platform(api, name="CloudVault Two", form_code="CV-FORM-9")

    first = f.digital_asset_payload(
        platform["id"],
        category=CATEGORY_CLOUD_STORAGE,
        account_handle="vault-1",
        quoted_value_cents=400033,
    )
    validate_success(api.create_digital_asset(estate["id"], first, fid_headers), 201)

    validate_error(
        api.create_digital_asset(estate["id"], dict(first), fid_headers),
        ERR_DUPLICATE_ASSET_HANDLE,
    )

    elsewhere = validate_success(
        api.create_digital_asset(
            estate["id"],
            f.digital_asset_payload(
                other_platform["id"],
                category=CATEGORY_CLOUD_STORAGE,
                account_handle="vault-1",
                quoted_value_cents=400033,
            ),
            fid_headers,
        ),
        201,
    )
    assert elsewhere["platform_id"] == other_platform["id"]
    assert elsewhere["account_handle"] == "vault-1"


# ─── System fields: the logical clock and the calling user ───────────────────
def _pending_death_certificate(api, case_number):
    """An estate with a fiduciary and one PENDING death certificate filed at the epoch."""
    estate, _, fid_headers = _estate_with_fiduciary(api, case_number)
    document = fx.add_document(
        api,
        estate["id"],
        f.document_payload(reference_number=f"DC-{case_number}"),
    )
    assert document["verification_status"] == DOC_PENDING
    return estate, fid_headers, document


def test_verification_records_the_clock_instant_and_the_acting_registrar(api):
    """Verifying a pending certificate after the clock has moved stamps the new instant and the registrar's own identifier.

    Verifying a `PENDING` document moves its `verification_status` to `VERIFIED`, writes the acting registrar's opaque `X-User-ID` into `verified_by_user_id` for audit, and stamps `verified_at` with the logical clock.

    Design: Corner/entities/system_fields_are_stamped_from_the_logical_clock_and_the_calling_user
    """
    fx.set_clock(api, CLOCK_EPOCH)
    _, _, document = _pending_death_certificate(api, "PR-2737-C07")

    moved = fx.set_clock(api, "2026-09-10T08:30:00Z")
    verified = validate_success(
        api.transition_document(
            document["id"],
            f.document_transition_payload(DOC_ACTION_VERIFY),
            COURT_REGISTRAR_HEADERS,
        ),
        200,
    )

    assert verified["id"] == document["id"]
    assert verified["verification_status"] == DOC_VERIFIED
    assert verified["verified_by_user_id"] == COURT_REGISTRAR_USER_ID
    assert _instant(verified["verified_at"]) == _instant(moved)


def test_moving_the_clock_leaves_earlier_stamps_alone(api):
    """The certificate keeps the creation instant it was filed at while its mutation stamp takes the clock's newer reading.

    Moving the clock re-stamps nothing retroactively — every `created_at`, `updated_at` and event stamp written after the move uses the new value, and previously written stamps are left alone.

    Design: Corner/entities/system_fields_are_stamped_from_the_logical_clock_and_the_calling_user
    """
    fx.set_clock(api, CLOCK_EPOCH)
    _, _, document = _pending_death_certificate(api, "PR-2737-C07B")
    assert _instant(document["created_at"]) == _instant(CLOCK_EPOCH)
    assert _instant(document["updated_at"]) == _instant(CLOCK_EPOCH)

    moved = fx.set_clock(api, "2026-09-10T08:30:00Z")
    fx.verify_document(api, document["id"])

    reread = validate_success(api.get_document(document["id"], COURT_REGISTRAR_HEADERS), 200)
    assert _instant(reread["created_at"]) == _instant(CLOCK_EPOCH), (
        "A clock move must not rewrite a stamp written before it"
    )
    assert _instant(reread["updated_at"]) == _instant(moved)


def test_one_mutation_lifts_the_version_by_exactly_one(api):
    """A document filed and then verified has been mutated once, so its version reads 2.

    `version` is an integer that starts at 1 on creation and increases by exactly 1 on every mutation of that record.

    Design: Corner/entities/system_fields_are_stamped_from_the_logical_clock_and_the_calling_user
    """
    fx.set_clock(api, CLOCK_EPOCH)
    _, _, document = _pending_death_certificate(api, "PR-2737-C07C")
    assert document["version"] == 1

    fx.set_clock(api, "2026-09-10T08:30:00Z")
    verified = validate_success(
        api.transition_document(
            document["id"],
            f.document_transition_payload(DOC_ACTION_VERIFY),
            COURT_REGISTRAR_HEADERS,
        ),
        200,
    )

    assert verified["version"] == 2
    assert_common_fields(verified, expected_version=2)


# ─── A request package and the documents it cites ────────────────────────────
def _two_estates_with_paperwork(api):
    """One provider, estate A with both documents, estate B with its own letters."""
    platform = fx.register_platform(api)
    estate_a, fid_a, fid_a_headers = _estate_with_fiduciary(api, "PR-2737-C08A")
    dc_a = fx.add_document(
        api, estate_a["id"], f.document_payload(reference_number="DC-C08A")
    )
    loa_a = fx.add_document(
        api,
        estate_a["id"],
        f.letters_document_payload(fid_a["id"], reference_number="LOA-C08A"),
    )
    estate_b, fid_b, _ = _estate_with_fiduciary(
        api,
        "PR-2737-C08B",
        decedent_name="Mica Reyes",
        date_of_death="2026-03-02",
        domicile_state="OR",
    )
    loa_b = fx.add_document(
        api,
        estate_b["id"],
        f.letters_document_payload(
            fid_b["id"],
            reference_number="LOA-C08B",
            issued_on="2026-03-20",
            jurisdiction="OR",
        ),
    )
    return {
        "platform": platform,
        "estate_a": estate_a,
        "fid_a_headers": fid_a_headers,
        "dc_a": dc_a,
        "loa_a": loa_a,
        "estate_b": estate_b,
        "loa_b": loa_b,
    }


@pytest.mark.parametrize(
    "field,expected_error",
    [
        ("letters_document_id", ERR_DOCUMENT_NOT_FOUND),
        ("platform_id", ERR_PLATFORM_NOT_FOUND),
    ],
    ids=["letters_document_id", "platform_id"],
)
def test_a_body_reference_that_names_nothing_is_a_not_found(api, field, expected_error):
    """A package citing an identifier no record answers to is refused with that reference's own not-found code.

    **Body-reference existence**, in this order: a `platform_id` in the body (`ERR_PLATFORM_NOT_FOUND`), a `fiduciary_id` in the body (`ERR_FIDUCIARY_NOT_FOUND`), then `death_certificate_document_id` and `letters_document_id` in that order (`ERR_DOCUMENT_NOT_FOUND`), then `beneficiary_designation_id` (`ERR_DESIGNATION_NOT_FOUND`) — all HTTP 404.

    Design: Corner/entities/platform_request_documents_must_belong_to_the_estate_and_match_their_slots
    """
    fx.set_clock(api, CLOCK_EPOCH)
    world = _two_estates_with_paperwork(api)

    payload = f.platform_request_payload(
        world["platform"]["id"],
        world["dc_a"]["id"],
        world["loa_a"]["id"],
        world["platform"]["form_code"],
    )
    payload[field] = NON_EXISTENT_UUID

    response = api.create_platform_request(
        world["estate_a"]["id"], payload, world["fid_a_headers"]
    )

    validate_error(response, expected_error)


def test_paperwork_from_another_estate_can_never_support_a_request(api):
    """Citing the letters filed on a different estate is refused as cross-estate paperwork.

    Both cited documents must belong to the same estate as the request, or the draft is rejected with `ERR_DOCUMENT_ESTATE_MISMATCH` — cross-estate paperwork can never support a request.

    Design: Corner/entities/platform_request_documents_must_belong_to_the_estate_and_match_their_slots
    """
    fx.set_clock(api, CLOCK_EPOCH)
    world = _two_estates_with_paperwork(api)

    response = api.create_platform_request(
        world["estate_a"]["id"],
        f.platform_request_payload(
            world["platform"]["id"],
            world["dc_a"]["id"],
            world["loa_b"]["id"],
            world["platform"]["form_code"],
        ),
        world["fid_a_headers"],
    )

    validate_error(response, ERR_DOCUMENT_ESTATE_MISMATCH)


def test_swapping_the_two_document_slots_is_a_type_error(api):
    """Putting the letters in the certificate slot and the certificate in the letters slot is a type error, not a verification failure.

    Swapping the two is a type error, rejected with `ERR_DOCUMENT_TYPE_MISMATCH` at HTTP 400, and is deliberately distinguished from a verification failure.

    Design: Corner/entities/platform_request_documents_must_belong_to_the_estate_and_match_their_slots
    """
    fx.set_clock(api, CLOCK_EPOCH)
    world = _two_estates_with_paperwork(api)

    response = api.create_platform_request(
        world["estate_a"]["id"],
        f.platform_request_payload(
            world["platform"]["id"],
            world["loa_a"]["id"],
            world["dc_a"]["id"],
            world["platform"]["form_code"],
        ),
        world["fid_a_headers"],
    )

    validate_error(response, ERR_DOCUMENT_TYPE_MISMATCH)


def test_the_estate_mismatch_is_reported_before_the_type_mismatch(api):
    """Another estate's letters placed in the certificate slot is wrong twice over, and the tenancy of the paperwork is reported first.

    7. **Referential consistency**, in order: documents belonging to the same estate as the request that cites them (`ERR_DOCUMENT_ESTATE_MISMATCH`, 409); the two cited documents being of the right types (`ERR_DOCUMENT_TYPE_MISMATCH`, 400); and the cited provider form code matching the provider's own (`ERR_PLATFORM_FORM_MISMATCH`, 409).

    Design: Corner/entities/platform_request_documents_must_belong_to_the_estate_and_match_their_slots
    """
    fx.set_clock(api, CLOCK_EPOCH)
    world = _two_estates_with_paperwork(api)

    response = api.create_platform_request(
        world["estate_a"]["id"],
        f.platform_request_payload(
            world["platform"]["id"],
            world["loa_b"]["id"],
            world["loa_a"]["id"],
            world["platform"]["form_code"],
        ),
        world["fid_a_headers"],
    )

    validate_error(response, ERR_DOCUMENT_ESTATE_MISMATCH)


def test_a_well_formed_package_opens_as_an_undecided_draft(api):
    """A package whose paperwork all lines up is stored as a draft with no review window, no decision and no resolution yet.

    A drafted package opens with `status` at `DRAFT`, `info_cycle_count` at 0, `review_window_start` and `review_window_end` null, and `decision`, `decision_note`, `missing_items`, `remediation_note`, `withdrawal_reason`, `resolved_scope` and `resolved_basis` all null, with `clamp_reason` at `NONE`.

    Design: Corner/entities/platform_request_documents_must_belong_to_the_estate_and_match_their_slots
    """
    fx.set_clock(api, CLOCK_EPOCH)
    world = _two_estates_with_paperwork(api)

    request = validate_success(
        api.create_platform_request(
            world["estate_a"]["id"],
            f.platform_request_payload(
                world["platform"]["id"],
                world["dc_a"]["id"],
                world["loa_a"]["id"],
                world["platform"]["form_code"],
            ),
            world["fid_a_headers"],
        ),
        201,
    )

    assert_fields(
        request,
        status=REQUEST_DRAFT,
        info_cycle_count=0,
        clamp_reason=CLAMP_NONE,
        estate_id=world["estate_a"]["id"],
        death_certificate_document_id=world["dc_a"]["id"],
        letters_document_id=world["loa_a"]["id"],
    )
    assert_null_fields(
        request,
        "review_window_start",
        "review_window_end",
        "decision",
        "decision_note",
        "missing_items",
        "remediation_note",
        "withdrawal_reason",
        "resolved_scope",
        "resolved_basis",
    )
    rows, meta = assert_envelope_array(
        api.list_platform_requests(
            world["fid_a_headers"], estate_id=world["estate_a"]["id"]
        )
    )
    assert meta["total_count"] == 1 and len(rows) == 1
    assert rows[0]["id"] == request["id"]


def test_documents_are_reachable_only_through_the_estate_that_filed_them(api):
    """Filtering the document register by estate returns each estate's own paperwork and nothing from the other.

    Documents may be filtered by `estate_id`, `fiduciary_id`, `doc_type` and `verification_status`.

    Design: Corner/entities/platform_request_documents_must_belong_to_the_estate_and_match_their_slots
    """
    fx.set_clock(api, CLOCK_EPOCH)
    world = _two_estates_with_paperwork(api)

    rows_a, meta_a = assert_envelope_array(
        api.list_documents(COURT_REGISTRAR_HEADERS, estate_id=world["estate_a"]["id"])
    )
    assert meta_a["total_count"] == 2
    assert {row["id"] for row in rows_a} == {world["dc_a"]["id"], world["loa_a"]["id"]}

    rows_b, meta_b = assert_envelope_array(
        api.list_documents(COURT_REGISTRAR_HEADERS, estate_id=world["estate_b"]["id"])
    )
    assert meta_b["total_count"] == 1
    assert [row["id"] for row in rows_b] == [world["loa_b"]["id"]]
