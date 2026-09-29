"""The refusal catalogue: which code a rejected TDR request must report.

Every scenario in this module is built so that exactly one rule of the program's
global evaluation ladder can fire, and then asserts the code that rule names.
Where two rules are violated at once on purpose — a settled sale whose conveyed
rights have been retired *and* whose 30-day reversal window has lapsed, or a
cure verification attempted by the inspector who recorded the finding on an
inspection that never entered `CURE_PENDING` — the ladder fixes which of the two
decides the response, and the test pins that one code rather than accepting
either.

The refusals are also checked for what they must *not* do: a rejected filing
leaves no row behind, a rejected proposal leaves the certificate `HELD` and
unencumbered, a rejected settlement moves no cash, and a rejected split leaves
the certificate's `version` where it was — which the surviving split proves by
re-using the version it observed before the two refusals.
"""
from test_helpers import (
    ADMIN_USER_ID,
    MONITOR_USER_ID,
    MONITOR_USER_ID_ALT,
    NON_EXISTENT_UUID,
    REVIEWER_USER_ID,
    TEST_USERS,
    ApiErrorId,
    allocate_redemption,
    allocate_redemption_payload,
    api_client,
    assert_certificate,
    assert_certificate_redemption,
    assert_market_transaction,
    assert_monitoring_inspection,
    assert_program_evaluation,
    assert_receiving_site_application,
    assert_same_date,
    assert_same_instant,
    assert_sending_parcel,
    assert_severance_application,
    compute_evaluation,
    create_active_receiving_area,
    create_active_sending_area,
    create_evaluation_payload,
    create_market_transaction_payload,
    create_receiving_site_application_payload,
    create_severance_application_payload,
    credit_party,
    cure_verification_payload,
    design_decision,
    designate_receiving_area,
    enroll_parcel,
    fetch_application,
    fetch_certificate,
    fetch_easement,
    fetch_inspection,
    fetch_party,
    fetch_receiving_area,
    fetch_receiving_site_application,
    fetch_redemption,
    fetch_sending_area,
    fetch_transaction,
    file_receiving_site_application,
    file_severance,
    get_success_data,
    make_developer_headers,
    make_landowner_headers,
    make_monitor_headers,
    make_reviewer_headers,
    program_cash_total,
    program_parties,
    propose_transaction,
    publish_appraisal_schedule,
    record_inspection,
    register_bank,
    register_developer,
    register_landowner,
    release_redemption,
    resubmit_design,
    resubmit_design_payload,
    retire_certificate_payload,
    retire_units,
    review_decision_payload,
    screen_application,
    set_clock,
    settle_transaction,
    setup_certified_severance,
    setup_developer_holding_certificate,
    split_certificate_payload,
    validate_error,
    validate_paginated,
)

ADMIN = TEST_USERS["admin_headers"]
CLOCK = "2026-08-10T00:00:00Z"
LATE_CLOCK = "2026-09-15T00:00:00Z"
PER_UNIT_VALUE_CENTS = 1_234_567
EQUITY_ADJUSTMENT_BPS = 250
ADJUSTED_PER_UNIT_CENTS = 1_265_431


def _headers(user_id=ADMIN_USER_ID, role="ProgramAdministrator", omit=()):
    """Well-formed operator headers, minus any header named in `omit`."""
    built = {"X-User-ID": user_id, "X-User-Role": role, "Content-Type": "application/json"}
    for name in omit:
        built.pop(name, None)
    return built


def _fetch_evaluation(evaluation_id):
    """Read one program evaluation back as the administrator."""
    return get_success_data(api_client.get_evaluation(evaluation_id, ADMIN))


def _zero_baseline_parcel():
    """A parcel whose whole acreage is constrained, so its baseline allocation is nil,
    enrolled in an ACTIVE area whose cap is nowhere near exhausted."""
    set_clock(CLOCK)
    landowner = register_landowner(neighborhood_code="NB-WEST")
    area = create_active_sending_area(
        neighborhood_code="NB-WEST",
        equity_tier="MODERATE",
        allocation_formula_version="V1_NET_ACRE",
        base_rate_units_per_acre=0.25,
        gross_discount_factor=0.80,
        sending_cap_units=200,
    )
    parcel = enroll_parcel(
        landowner["id"], area["id"],
        gross_acres=40.00, constrained_acres=40.00, soil_class="LOCAL",
        existing_dwelling_units=0,
    )
    return landowner, area, parcel


def _priced_certificate():
    """A 22-unit certificate held by its landowner, an unfunded developer, the bank,
    and an NB-EAST appraisal schedule that puts the 22-unit reference at 27839482."""
    scenario = setup_certified_severance(
        units=22, clock=CLOCK, equity_tier="UNDERSERVED", neighborhood_code="NB-EAST"
    )
    scenario["developer"] = register_developer(neighborhood_code="NB-CORE")
    scenario["bank"] = register_bank(neighborhood_code="NB-CORE")
    scenario["schedule"] = publish_appraisal_schedule(
        neighborhood_code="NB-EAST",
        per_unit_value_cents=PER_UNIT_VALUE_CENTS,
        equity_adjustment_bps=EQUITY_ADJUSTMENT_BPS,
        effective_from="2026-01-01",
        effective_to="2027-01-01",
    )
    return scenario


def _settled_sale_with_retired_rights():
    """A whole 22-unit certificate sold PRIVATE for 30000000 and settled on the
    2026-08-10 clock, whose conveyed rights the buyer then retires in full."""
    scenario = setup_developer_holding_certificate(
        units=22, clock=CLOCK, equity_tier="UNDERSERVED",
        per_unit_value_cents=PER_UNIT_VALUE_CENTS,
        equity_adjustment_bps=EQUITY_ADJUSTMENT_BPS,
        agreed_price_cents=30_000_000,
    )
    developer = scenario["developer"]
    scenario["certificate"] = retire_units(
        scenario["certificate"]["id"], 22,
        actor_headers=make_developer_headers(developer["id"]),
        reason="permanent extinguishment by the buyer",
    )
    scenario["easement"] = fetch_easement(scenario["easement"]["id"])
    return scenario


def _partly_frozen_backing_pool():
    """An over-collateralized receiving-site application — 3 units allocated against a
    required 2 — one of whose two source easements is then driven out of compliance,
    plus a second application in an area that admits only one foreign sending code.
    """
    set_clock(CLOCK)
    landowner = register_landowner(neighborhood_code="NB-EAST")
    developer = register_developer(neighborhood_code="NB-CORE")
    bank = register_bank(neighborhood_code="NB-CORE")
    credit_party(developer["id"], 6_000_000)
    area = create_active_sending_area(
        neighborhood_code="NB-EAST",
        equity_tier="UNDERSERVED",
        allocation_formula_version="V1_NET_ACRE",
        base_rate_units_per_acre=0.25,
        gross_discount_factor=0.80,
        sending_cap_units=200,
    )
    publish_appraisal_schedule(
        neighborhood_code="NB-EAST",
        per_unit_value_cents=PER_UNIT_VALUE_CENTS,
        equity_adjustment_bps=EQUITY_ADJUSTMENT_BPS,
        effective_from="2026-01-01",
        effective_to="2027-01-01",
    )
    certificates = {}
    for key, units in (("a", 1), ("b", 3)):
        parcel = enroll_parcel(
            landowner["id"], area["id"],
            gross_acres=40.00, constrained_acres=0.00, soil_class="LOCAL",
            existing_dwelling_units=0,
        )
        application = file_severance(parcel["id"], landowner["id"], units)
        screen_application(application["id"])
        get_success_data(api_client.review_severance_application(
            application["id"], review_decision_payload("APPROVE"),
            make_reviewer_headers(REVIEWER_USER_ID),
        ))
        certificate = get_success_data(
            api_client.certify_severance_application(application["id"], ADMIN)
        )
        transaction = propose_transaction(
            certificate["id"], landowner["id"], developer["id"], units=units,
            channel="PRIVATE", agreed_price_cents=ADJUSTED_PER_UNIT_CENTS * units,
        )
        settle_transaction(transaction["id"])
        certificates[key] = fetch_certificate(certificate["id"])

    core_area = create_active_receiving_area(
        neighborhood_code="NB-CORE",
        base_density_units_per_acre=4.00,
        max_bonus_pct=0.35,
        absorption_cap_units=500,
        design_review_required=False,
        eligible_sending_area_codes=[],
    )
    north_area = create_active_receiving_area(
        neighborhood_code="NB-NORTH",
        base_density_units_per_acre=4.00,
        max_bonus_pct=0.35,
        absorption_cap_units=500,
        design_review_required=False,
        eligible_sending_area_codes=["SA-WEST"],
    )
    rsa = file_receiving_site_application(
        developer["id"], core_area["id"], site_acres=2.50, requested_bonus_units=20
    )
    redemption_a = allocate_redemption(
        rsa["id"], developer["id"], certificates["a"]["id"], 1
    )
    redemption_b = allocate_redemption(
        rsa["id"], developer["id"], certificates["b"]["id"], 2
    )
    north_rsa = file_receiving_site_application(
        developer["id"], north_area["id"], site_acres=2.50, requested_bonus_units=20
    )
    inspection = record_inspection(
        fetch_certificate(certificates["a"]["id"])["conservation_easement_id"],
        "2026-08-10", "MAJOR_VIOLATION", 4.00, MONITOR_USER_ID,
        note="restricted area cleared and graded",
    )
    return {
        "landowner": landowner,
        "developer": developer,
        "bank": bank,
        "sending_area": fetch_sending_area(area["id"]),
        "certificate_a": fetch_certificate(certificates["a"]["id"]),
        "certificate_b": fetch_certificate(certificates["b"]["id"]),
        "core_area": fetch_receiving_area(core_area["id"]),
        "north_area": fetch_receiving_area(north_area["id"]),
        "rsa": fetch_receiving_site_application(rsa["id"]),
        "north_rsa": fetch_receiving_site_application(north_rsa["id"]),
        "redemption_a": fetch_redemption(redemption_a["id"]),
        "redemption_b": fetch_redemption(redemption_b["id"]),
        "inspection": fetch_inspection(inspection["id"]),
    }


class TestUnresolvedPathIdentifiers:
    """Fourteen entities, fourteen not-found codes, one fabricated identifier."""

    def test_each_detail_read_reports_the_not_found_code_of_its_own_entity(self):
        """The same unresolvable identifier must select a different code per route.

        PRD §2.9: "Path identifiers are resolved strictly left to right, and the
        leftmost identifier that fails to resolve decides the error. Each entity has
        its own not-found code, all at HTTP 404: `ERR_PARTY_NOT_FOUND`,
        `ERR_SENDING_AREA_NOT_FOUND`, `ERR_RECEIVING_AREA_NOT_FOUND`,
        `ERR_APPRAISAL_SCHEDULE_NOT_FOUND`, `ERR_SENDING_PARCEL_NOT_FOUND`,
        `ERR_SEVERANCE_APPLICATION_NOT_FOUND`, `ERR_CONSERVATION_EASEMENT_NOT_FOUND`,
        `ERR_CERTIFICATE_NOT_FOUND`, `ERR_CERTIFICATE_TRANSFER_NOT_FOUND`,
        `ERR_MARKET_TRANSACTION_NOT_FOUND`, `ERR_RECEIVING_SITE_APPLICATION_NOT_FOUND`,
        `ERR_CERTIFICATE_REDEMPTION_NOT_FOUND`, `ERR_MONITORING_INSPECTION_NOT_FOUND`,
        and `ERR_PROGRAM_EVALUATION_NOT_FOUND`."

        PRD §2.10: "3. **Path existence** — every identifier in the path resolves,
        left to right; otherwise the matching not-found code (404). Applies to every
        endpoint carrying a path identifier."

        Design: Corner/errors/every_unresolved_path_id_reports_its_own_not_found_code
        """
        set_clock(CLOCK)
        probes = [
            ("party", api_client.get_party, ApiErrorId.ERR_PARTY_NOT_FOUND),
            ("sending area", api_client.get_sending_area, ApiErrorId.ERR_SENDING_AREA_NOT_FOUND),
            ("receiving area", api_client.get_receiving_area,
             ApiErrorId.ERR_RECEIVING_AREA_NOT_FOUND),
            ("appraisal schedule", api_client.get_appraisal_schedule,
             ApiErrorId.ERR_APPRAISAL_SCHEDULE_NOT_FOUND),
            ("sending parcel", api_client.get_sending_parcel,
             ApiErrorId.ERR_SENDING_PARCEL_NOT_FOUND),
            ("severance application", api_client.get_severance_application,
             ApiErrorId.ERR_SEVERANCE_APPLICATION_NOT_FOUND),
            ("conservation easement", api_client.get_conservation_easement,
             ApiErrorId.ERR_CONSERVATION_EASEMENT_NOT_FOUND),
            ("certificate", api_client.get_certificate, ApiErrorId.ERR_CERTIFICATE_NOT_FOUND),
            ("certificate transfer", api_client.get_certificate_transfer,
             ApiErrorId.ERR_CERTIFICATE_TRANSFER_NOT_FOUND),
            ("market transaction", api_client.get_market_transaction,
             ApiErrorId.ERR_MARKET_TRANSACTION_NOT_FOUND),
            ("receiving-site application", api_client.get_receiving_site_application,
             ApiErrorId.ERR_RECEIVING_SITE_APPLICATION_NOT_FOUND),
            ("certificate redemption", api_client.get_certificate_redemption,
             ApiErrorId.ERR_CERTIFICATE_REDEMPTION_NOT_FOUND),
            ("monitoring inspection", api_client.get_monitoring_inspection,
             ApiErrorId.ERR_MONITORING_INSPECTION_NOT_FOUND),
            ("program evaluation", api_client.get_evaluation,
             ApiErrorId.ERR_PROGRAM_EVALUATION_NOT_FOUND),
        ]
        for label, read, error_id in probes:
            response = read(NON_EXISTENT_UUID, ADMIN)
            validate_error(response, error_id.value)
            body = response.json()
            assert body["data"]["message"], (
                f"the {label} not-found response must carry a human-readable message, "
                f"got {body['data']!r}"
            )

    def test_an_unresolved_parent_on_a_sub_resource_listing_reports_the_parent_code(self):
        """The inspection listing hangs off an easement, so the easement decides the code.

        PRD §2.9: "Path identifiers are resolved strictly left to right, and the
        leftmost identifier that fails to resolve decides the error."

        PRD §2.10: "3. **Path existence** — every identifier in the path resolves,
        left to right; otherwise the matching not-found code (404). Applies to every
        endpoint carrying a path identifier."

        Design: Corner/errors/every_unresolved_path_id_reports_its_own_not_found_code
        """
        set_clock(CLOCK)
        response = api_client.list_easement_inspections(NON_EXISTENT_UUID, ADMIN)
        validate_error(response, ApiErrorId.ERR_CONSERVATION_EASEMENT_NOT_FOUND.value)
        assert response.json()["response_type"] == "error", (
            "an unresolved easement must not yield an empty 200 inspection page"
        )

    def test_a_write_against_an_unresolved_path_identifier_reports_the_path_code(self):
        """A well-formed body cannot rescue a path identifier that does not resolve.

        PRD §2.10: "3. **Path existence** — every identifier in the path resolves,
        left to right; otherwise the matching not-found code (404). Applies to every
        endpoint carrying a path identifier."

        PRD §2.10: "4. **Request shape** — every required input field is present;
        types, enum membership, string lengths, decimal places and numeric ranges are
        honoured; `period_start` is not after `period_end`; `effective_from` is
        strictly before `effective_to`; any `units` figure is greater than zero; every
        field whose name ends in `_cents` is a non-negative integer; unknown fields are
        ignored rather than rejected. A failure here is `ERR_INVALID_REQUEST` (400).
        Applies to every endpoint with a request body or query parameters."

        Design: Corner/errors/every_unresolved_path_id_reports_its_own_not_found_code
        """
        set_clock(CLOCK)
        validate_error(
            api_client.activate_sending_area(NON_EXISTENT_UUID, ADMIN, {}),
            ApiErrorId.ERR_SENDING_AREA_NOT_FOUND.value,
        )
        validate_error(
            api_client.screen_severance_application(
                NON_EXISTENT_UUID, make_reviewer_headers(REVIEWER_USER_ID), {}
            ),
            ApiErrorId.ERR_SEVERANCE_APPLICATION_NOT_FOUND.value,
        )
        validate_error(
            api_client.split_certificate(
                NON_EXISTENT_UUID, split_certificate_payload(1, 1), ADMIN
            ),
            ApiErrorId.ERR_CERTIFICATE_NOT_FOUND.value,
        )
        validate_error(
            api_client.settle_market_transaction(NON_EXISTENT_UUID, ADMIN, {}),
            ApiErrorId.ERR_MARKET_TRANSACTION_NOT_FOUND.value,
        )


class TestAuthenticationOutranksEverythingElse:
    """A caller who has not identified itself is refused before any other question."""

    def test_a_missing_empty_or_undeclared_role_header_is_rejected_as_unauthenticated(self):
        """The same listing succeeds with both headers and fails four ways without them.

        PRD §2.1: "Every request must carry two headers: `X-User-ID`, identifying the
        caller, and `X-User-Role`, naming the capacity in which the caller acts. If
        either header is missing or empty, or if `X-User-Role` is not one of the six
        role names below, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401).
        If the headers are well formed but the named role is not authorized for the
        endpoint being called, the request is rejected with `ERR_ROLE_NOT_PERMITTED`
        (HTTP 403). The six roles are `ProgramAdministrator`, `SeveranceReviewer`,
        `DesignReviewBoard`, `EasementMonitor`, `Landowner`, and `Developer`."

        PRD §2.10: "1. **Authentication** — both headers present and non-empty and
        `X-User-Role` names a declared role; otherwise `ERR_UNAUTHENTICATED` (401).
        Applies to every endpoint."

        Design: Corner/errors/a_missing_or_undeclared_role_header_is_rejected_before_existence
        """
        set_clock(CLOCK)
        baseline, meta = validate_paginated(
            api_client.list_parties(ADMIN, params={"limit": 10, "offset": 0})
        )
        assert baseline == [], f"the party register starts empty, got {baseline!r}"
        assert meta["total_count"] == 0, (
            f"total_count must be 0 on an empty register, got {meta['total_count']}"
        )

        for label, headers in (
            ("no X-User-Role header", _headers(omit=("X-User-Role",))),
            ("an empty X-User-Role header", _headers(role="")),
            ("no X-User-ID header", _headers(omit=("X-User-ID",))),
            ("an undeclared role", _headers(role="Auditor")),
        ):
            response = api_client.list_parties(headers, params={"limit": 10, "offset": 0})
            validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED.value)
            assert response.json()["data"]["error_id"] == (
                ApiErrorId.ERR_UNAUTHENTICATED.value
            ), f"{label} must be an authentication failure, not an authorization failure"

    def test_authentication_precedes_path_existence(self):
        """An unauthenticated read of a row that does not exist is a 401, not a 404.

        PRD §2.10: "When several rules could reject the same request, the outcome is
        not left to implementation order. The checks below form one global ladder,
        evaluated strictly from the top; the first check that fails decides the
        response, and no later check is consulted. Authentication precedes
        authorization, existence precedes ownership, safety precedes constraint, and
        fiscal checks always come last."

        PRD §2.10: "1. **Authentication** — both headers present and non-empty and
        `X-User-Role` names a declared role; otherwise `ERR_UNAUTHENTICATED` (401).
        Applies to every endpoint."

        PRD §2.10: "3. **Path existence** — every identifier in the path resolves,
        left to right; otherwise the matching not-found code (404). Applies to every
        endpoint carrying a path identifier."

        Design: Corner/errors/a_missing_or_undeclared_role_header_is_rejected_before_existence
        """
        set_clock(CLOCK)
        validate_error(
            api_client.get_party(NON_EXISTENT_UUID, _headers(omit=("X-User-Role",))),
            ApiErrorId.ERR_UNAUTHENTICATED.value,
        )
        validate_error(
            api_client.get_party(NON_EXISTENT_UUID, ADMIN),
            ApiErrorId.ERR_PARTY_NOT_FOUND.value,
        )

    def test_an_unauthenticated_write_persists_nothing(self):
        """A 401 on a creation endpoint must leave the register untouched.

        PRD §2.1: "If either header is missing or empty, or if `X-User-Role` is not one
        of the six role names below, the request is rejected with `ERR_UNAUTHENTICATED`
        (HTTP 401)."

        PRD §2.10: "1. **Authentication** — both headers present and non-empty and
        `X-User-Role` names a declared role; otherwise `ERR_UNAUTHENTICATED` (401).
        Applies to every endpoint."

        Design: Corner/errors/a_missing_or_undeclared_role_header_is_rejected_before_existence
        """
        set_clock(CLOCK)
        payload = {
            "kind": "LANDOWNER",
            "legal_name": "Ridge Farm LLC",
            "contact_email": "ridge@example.org",
            "neighborhood_code": "NB-EAST",
        }
        validate_error(
            api_client.create_party(payload, _headers(omit=("X-User-Role",))),
            ApiErrorId.ERR_UNAUTHENTICATED.value,
        )
        rows, meta = validate_paginated(api_client.list_parties(ADMIN))
        assert meta["total_count"] == 0, (
            f"an unauthenticated POST must create no Party row, found {meta['total_count']}"
        )
        assert rows == [], f"expected an empty party register, got {rows!r}"


class TestSendingSideIntakeAndGrantGuards:
    """Which bucket is empty, and when the program looks at it."""

    def test_a_fully_severed_parcel_cannot_carry_another_filing(self):
        """The parcel has nothing left to give, and its area is still wide open.

        PRD §3.4: "Three further gates guard intake: the parcel's sending area must be
        `ACTIVE`, the parcel's `parcel_status` must not be `FULLY_SEVERED` (a fully
        severed parcel has nothing left to give, and the filing is rejected with
        `ERR_PARCEL_FULLY_SEVERED`), and the parcel must not already carry an
        application in a non-terminal status — meaning `SUBMITTED`, `UNDER_REVIEW`,
        `REVISION_REQUESTED`, or `APPROVED` — which is rejected with
        `ERR_PARCEL_HAS_OPEN_APPLICATION`."

        PRD §2.10: "22. The sending parcel's `parcel_status` is not `FULLY_SEVERED`;
        otherwise `ERR_PARCEL_FULLY_SEVERED` (409). Applies to severance filing."

        Design: Corner/errors/sending_side_intake_and_grant_guards_each_report_their_own_code
        """
        scenario = setup_certified_severance(units=22, clock=CLOCK)
        landowner, parcel, area = scenario["landowner"], scenario["parcel"], scenario["area"]
        assert_sending_parcel(parcel)
        assert parcel["parcel_status"] == "FULLY_SEVERED", (
            f"severing the whole baseline must exhaust the parcel, got {parcel['parcel_status']}"
        )
        assert parcel["remaining_units"] == 0, (
            f"an exhausted parcel keeps no rights, got {parcel['remaining_units']}"
        )
        assert area["status"] == "ACTIVE", (
            "the area cap is nowhere near exhausted, so only the parcel gate may fire; "
            f"got area status {area['status']}"
        )

        response = api_client.create_severance_application(
            create_severance_application_payload(parcel["id"], landowner["id"], 1),
            make_landowner_headers(landowner["id"]),
        )
        validate_error(response, ApiErrorId.ERR_PARCEL_FULLY_SEVERED.value)

        _, meta = validate_paginated(api_client.list_severance_applications(
            ADMIN, params={"sending_parcel_id": parcel["id"]}
        ))
        assert meta["total_count"] == 1, (
            f"the refused filing must create no second application, found {meta['total_count']}"
        )

    def test_a_parcel_with_a_live_application_cannot_carry_a_second_one(self):
        """One parcel, at most one live application: severances are strictly sequential.

        PRD §3.4: "Three further gates guard intake: the parcel's sending area must be
        `ACTIVE`, the parcel's `parcel_status` must not be `FULLY_SEVERED` (a fully
        severed parcel has nothing left to give, and the filing is rejected with
        `ERR_PARCEL_FULLY_SEVERED`), and the parcel must not already carry an
        application in a non-terminal status — meaning `SUBMITTED`, `UNDER_REVIEW`,
        `REVISION_REQUESTED`, or `APPROVED` — which is rejected with
        `ERR_PARCEL_HAS_OPEN_APPLICATION`."

        PRD §2.10: "35. The sending parcel has no severance application in a
        non-terminal status; otherwise `ERR_PARCEL_HAS_OPEN_APPLICATION` (409)."

        Design: Corner/errors/sending_side_intake_and_grant_guards_each_report_their_own_code
        """
        set_clock(CLOCK)
        landowner = register_landowner(neighborhood_code="NB-EAST")
        area = create_active_sending_area(
            neighborhood_code="NB-EAST",
            equity_tier="UNDERSERVED",
            allocation_formula_version="V1_NET_ACRE",
            base_rate_units_per_acre=0.25,
            gross_discount_factor=0.80,
            sending_cap_units=200,
        )
        parcel = enroll_parcel(
            landowner["id"], area["id"],
            gross_acres=100.00, constrained_acres=22.00, soil_class="PRIME",
            existing_dwelling_units=2,
        )
        first = file_severance(parcel["id"], landowner["id"], 10)
        assert_severance_application(first)
        assert first["status"] == "SUBMITTED", (
            f"a fresh filing opens in SUBMITTED, got {first['status']}"
        )

        response = api_client.create_severance_application(
            create_severance_application_payload(parcel["id"], landowner["id"], 5),
            make_landowner_headers(landowner["id"]),
        )
        validate_error(response, ApiErrorId.ERR_PARCEL_HAS_OPEN_APPLICATION.value)

        _, meta = validate_paginated(api_client.list_severance_applications(
            ADMIN, params={"sending_parcel_id": parcel["id"]}
        ))
        assert meta["total_count"] == 1, (
            f"the parcel keeps exactly one application, found {meta['total_count']}"
        )

    def test_an_approval_that_would_grant_no_units_is_refused_with_no_allocable_units(self):
        """A zero-baseline parcel in an area with capacity to spare fails the min(), not the cap.

        PRD §3.4: "The grant computation is a two-bucket waterfall in whole units, with
        no rounding anywhere. The parcel bucket is the parcel's `remaining_units`. The
        area bucket is the area's `sending_cap_units` less its `severed_units_total`. If
        the area bucket is zero or negative, the area has no unsevered capacity at all
        and the decision is rejected with `ERR_SENDING_CAP_EXHAUSTED`. Otherwise
        `allocated_units` is the smallest of three quantities: the `requested_units` on
        the application, the parcel bucket, and the area bucket. If that smallest
        quantity is not at least one, the approval is rejected with
        `ERR_NO_ALLOCABLE_UNITS`."

        PRD §2.10: "46. The severance grant would allocate at least one unit while the
        area still has capacity; a grant of zero units with capacity remaining is
        `ERR_NO_ALLOCABLE_UNITS` (422). Applies to severance review decisions."

        Design: Corner/errors/sending_side_intake_and_grant_guards_each_report_their_own_code
        """
        landowner, area, parcel = _zero_baseline_parcel()
        assert parcel["baseline_allocation_units"] == 0, (
            "an entirely constrained parcel earns no baseline allocation, got "
            f"{parcel['baseline_allocation_units']}"
        )
        assert parcel["parcel_status"] == "UNSEVERED", (
            f"a zero-baseline parcel is not fully severed, got {parcel['parcel_status']}"
        )
        assert area["sending_cap_units"] - area["severed_units_total"] > 0, (
            "the area bucket must stay positive so that only the min() can fail"
        )

        application = file_severance(parcel["id"], landowner["id"], 5)
        screen_application(application["id"])
        response = api_client.review_severance_application(
            application["id"], review_decision_payload("APPROVE"),
            make_reviewer_headers(REVIEWER_USER_ID),
        )
        validate_error(response, ApiErrorId.ERR_NO_ALLOCABLE_UNITS.value)

        after = fetch_application(application["id"])
        assert after["status"] == "UNDER_REVIEW", (
            f"a refused decision leaves the application in review, got {after['status']}"
        )
        assert after["allocated_units"] == 0, (
            f"a refused decision grants nothing, got {after['allocated_units']}"
        )
        assert fetch_sending_area(area["id"])["severed_units_total"] == 0, (
            "a refused decision severs nothing from the area"
        )


class TestProposalBandAndSettlementFunding:
    """The band is tested when the price is named; the cash is tested at settlement."""

    def test_a_price_outside_the_deviation_band_is_refused_at_proposal(self):
        """40000000 against a 27839482 reference is 4368 bps away, well past the band.

        PRD §3.7: "`applied_per_unit_value_cents` is the selected schedule's
        `per_unit_value_cents` multiplied by one plus its `equity_adjustment_bps` divided
        by ten thousand, rounded half up to a whole number of cents — the rounding
        happens on the per-unit figure, before any multiplication by units."

        PRD §3.7: "`appraised_reference_cents` is then `applied_per_unit_value_cents`
        multiplied by `units`."

        PRD §3.7: "If the absolute value of `price_deviation_bps` is strictly greater
        than 3000 basis points — thirty percent away from the appraised reference in
        either direction — the proposal is rejected with
        `ERR_PRICE_DEVIATION_EXCEEDS_BAND`."

        PRD §2.10: "44. The proposed price sits inside the deviation band; otherwise
        `ERR_PRICE_DEVIATION_EXCEEDS_BAND` (422). Applies to transaction proposal."

        Design: Corner/errors/proposal_price_band_and_settlement_funding_guards
        """
        scenario = _priced_certificate()
        certificate, landowner = scenario["certificate"], scenario["landowner"]
        developer = scenario["developer"]

        response = api_client.create_market_transaction(
            create_market_transaction_payload(
                certificate["id"], landowner["id"], developer["id"], 22,
                "PRIVATE", "WHOLE", agreed_price_cents=40_000_000,
            ),
            make_landowner_headers(landowner["id"]),
        )
        validate_error(response, ApiErrorId.ERR_PRICE_DEVIATION_EXCEEDS_BAND.value)

        _, meta = validate_paginated(api_client.list_market_transactions(ADMIN))
        assert meta["total_count"] == 0, (
            f"a refused proposal must create no transaction row, found {meta['total_count']}"
        )
        after = fetch_certificate(certificate["id"])
        assert_certificate(after)
        assert after["market_status"] == "HELD", (
            f"a refused proposal must not encumber the certificate, got {after['market_status']}"
        )
        assert after["units_encumbered"] == 0, (
            f"a refused proposal encumbers nothing, got {after['units_encumbered']}"
        )

    def test_settlement_is_refused_when_the_buyer_was_never_funded(self):
        """A deal exactly on the band is accepted, and then fails for a fiscal reason instead.

        PRD §3.7: "The comparison is strictly greater-than, so a deal landing exactly on
        3000 basis points is accepted."

        PRD §3.7: "An accepted proposal opens in `status` `PROPOSED`, moves the
        certificate `HELD → UNDER_CONTRACT`, grows the certificate's `units_encumbered`
        by the traded `units`, and increments the certificate's `version`.
        `program_fee_cents`, `equity_surcharge_cents`, and `net_to_seller_cents` all stay
        at 0 until settlement, and `conveyed_certificate_id`, `settled_at`,
        `reversed_at`, and `reversal_reason` all stay unset."

        PRD §3.7: "It requires the transaction to be `PROPOSED`, otherwise
        `ERR_TRANSACTION_NOT_PROPOSED`; both the buyer and the seller party to be
        `ACTIVE`, otherwise `ERR_PARTY_SUSPENDED`; the certificate's `market_status` to
        be `UNDER_CONTRACT`; the backing easement's `compliance_status` to be
        `COMPLIANT` or `CURED`; the traded units to still be available on the
        certificate; and the buyer's `cash_balance_cents` to be at least
        `gross_price_cents`, otherwise `ERR_INSUFFICIENT_FUNDS`."

        Design: Corner/errors/proposal_price_band_and_settlement_funding_guards
        """
        scenario = _priced_certificate()
        certificate, landowner = scenario["certificate"], scenario["landowner"]
        developer, bank = scenario["developer"], scenario["bank"]

        transaction = propose_transaction(
            certificate["id"], landowner["id"], developer["id"], units=22,
            channel="PRIVATE", agreed_price_cents=36_191_327,
        )
        assert_market_transaction(transaction)
        assert transaction["applied_per_unit_value_cents"] == 1_265_431, (
            "1234567 cents adjusted by 250 bps rounds half up to 1265431, got "
            f"{transaction['applied_per_unit_value_cents']}"
        )
        assert transaction["appraised_reference_cents"] == 27_839_482, (
            f"1265431 x 22 units is 27839482, got {transaction['appraised_reference_cents']}"
        )
        assert transaction["price_deviation_bps"] == 3000, (
            f"36191327 sits exactly 3000 bps above the reference, got "
            f"{transaction['price_deviation_bps']}"
        )
        assert transaction["gross_price_cents"] == 36_191_327, (
            f"a PRIVATE gross price is the agreed price exactly, got "
            f"{transaction['gross_price_cents']}"
        )
        under_contract = fetch_certificate(certificate["id"])
        assert under_contract["market_status"] == "UNDER_CONTRACT", (
            f"an accepted proposal encumbers the certificate, got "
            f"{under_contract['market_status']}"
        )
        assert under_contract["units_encumbered"] == 22, (
            f"all 22 traded units are encumbered, got {under_contract['units_encumbered']}"
        )

        response = api_client.settle_market_transaction(transaction["id"], ADMIN, {})
        validate_error(response, ApiErrorId.ERR_INSUFFICIENT_FUNDS.value)

        after = fetch_transaction(transaction["id"])
        assert after["status"] == "PROPOSED", (
            f"a refused settlement leaves the deal PROPOSED, got {after['status']}"
        )
        assert after["settled_at"] is None, (
            f"a refused settlement sets no settled_at, got {after['settled_at']!r}"
        )
        for field in ("program_fee_cents", "equity_surcharge_cents", "net_to_seller_cents"):
            assert after[field] == 0, (
                f"{field} stays at 0 until settlement, got {after[field]}"
            )
        assert fetch_party(landowner["id"])["cash_balance_cents"] == 0, "no seller proceeds moved"
        assert fetch_party(developer["id"])["cash_balance_cents"] == 0, "no buyer cash moved"
        assert fetch_party(bank["id"])["fee_revenue_cents"] == 0, "no program fee accrued"
        assert fetch_certificate(certificate["id"])["holder_party_id"] == landowner["id"], (
            "title stays with the seller until settlement"
        )
        _, transfers_meta = validate_paginated(api_client.list_certificate_transfers(
            ADMIN, params={"certificate_id": certificate["id"]}
        ))
        assert transfers_meta["total_count"] == 1, (
            "only the ISSUANCE row exists after a refused settlement, found "
            f"{transfers_meta['total_count']}"
        )


class TestReversalGuards:
    """Two independent reasons a settled sale cannot be unwound, and their order."""

    def test_retiring_the_conveyed_rights_makes_a_settled_deal_irreversible(self):
        """Inside the window, the consumed lineage alone refuses the reversal.

        PRD §3.7: "The conveyed certificate must have `units_redeemed`,
        `units_encumbered`, and `units_retired` all at zero — if any of the conveyed
        rights have been committed or consumed since settlement, the reversal is again
        rejected with `ERR_REVERSAL_NOT_PERMITTED`."

        PRD §3.6: "`units_retired` grows by `units` and `units_remaining` is recomputed;
        when `units_remaining` reaches zero the `lifecycle_status` becomes `RETIRED`, and
        it does so even if redemption also contributed to emptying the certificate —
        retirement outranks redemption when both reduced the same certificate to zero."

        PRD §3.6: "A `RETIREMENT` chain-of-title row is appended with no transferee and
        no price, the backing easement's `units_retired` and `units_outstanding` are
        recomputed (leaving `units_issued_total` untouched), the holder's `units_held`
        and `certificates_held_count` are recomputed, and the certificate's `version` is
        incremented."

        PRD §2.10: "42. The settled transaction is still cleanly reversible; otherwise
        `ERR_REVERSAL_NOT_PERMITTED` (409)."

        Design: Corner/errors/reversal_guards_report_the_temporal_refusal_before_the_lineage_refusal
        """
        scenario = _settled_sale_with_retired_rights()
        certificate, easement = scenario["certificate"], scenario["easement"]
        assert_certificate(certificate)
        assert certificate["units_retired"] == 22, (
            f"the buyer retired all 22 conveyed units, got {certificate['units_retired']}"
        )
        assert certificate["units_remaining"] == 0, (
            f"nothing survives the retirement, got {certificate['units_remaining']}"
        )
        assert certificate["lifecycle_status"] == "RETIRED", (
            f"an emptied certificate is RETIRED, got {certificate['lifecycle_status']}"
        )
        assert easement["units_retired"] == 22, (
            f"the easement records the extinguishment, got {easement['units_retired']}"
        )
        assert easement["units_outstanding"] == 0, (
            f"no rights remain outstanding, got {easement['units_outstanding']}"
        )
        assert easement["units_issued_total"] == 22, (
            f"retirement never rewrites units_issued_total, got {easement['units_issued_total']}"
        )

        response = api_client.reverse_market_transaction(
            scenario["transaction"]["id"], {"reversal_reason": "TITLE_DEFECT"}, ADMIN
        )
        validate_error(response, ApiErrorId.ERR_REVERSAL_NOT_PERMITTED.value)

        after = fetch_transaction(scenario["transaction"]["id"])
        assert after["status"] == "SETTLED", (
            f"a refused reversal leaves the deal SETTLED, got {after['status']}"
        )
        assert after["reversed_at"] is None, (
            f"a refused reversal sets no reversed_at, got {after['reversed_at']!r}"
        )
        assert after["reversal_reason"] is None, (
            f"a refused reversal records no reason, got {after['reversal_reason']!r}"
        )

    def test_a_lapsed_window_outranks_the_consumed_lineage(self):
        """With both preconditions broken, the temporal rung decides the code.

        PRD §3.7: "And the current logical clock must be no later than 30 days after
        `settled_at`: exactly 30 days after settlement is still reversible, 31 days is
        not, and a late attempt is rejected with `ERR_REVERSAL_WINDOW_EXPIRED`."

        PRD §2.10: "the first check that fails decides the response, and no later check
        is consulted"

        PRD §2.10: "32. The reversal falls inside the reversal window measured from
        `settled_at`; otherwise `ERR_REVERSAL_WINDOW_EXPIRED` (409)."

        PRD §2.10: "42. The settled transaction is still cleanly reversible; otherwise
        `ERR_REVERSAL_NOT_PERMITTED` (409)."

        PRD §3.6: "Every event in a certificate's life appends one immutable
        **CertificateTransfer** row: an issuance at certification, a split-out when units
        leave for a child, a sale under one of the three channels, a redemption when
        units back a permit, a retirement when units are extinguished, and a reversal
        when a settled sale is undone."

        Design: Corner/errors/reversal_guards_report_the_temporal_refusal_before_the_lineage_refusal
        """
        scenario = _settled_sale_with_retired_rights()
        transaction_id = scenario["transaction"]["id"]
        cash_before = program_cash_total(program_parties())

        set_clock(LATE_CLOCK)
        response = api_client.reverse_market_transaction(
            transaction_id, {"reversal_reason": "TITLE_DEFECT"}, ADMIN
        )
        validate_error(response, ApiErrorId.ERR_REVERSAL_WINDOW_EXPIRED.value)

        after = fetch_transaction(transaction_id)
        assert after["status"] == "SETTLED", (
            f"a refused reversal leaves the deal SETTLED, got {after['status']}"
        )
        assert after["reversed_at"] is None, (
            f"a refused reversal sets no reversed_at, got {after['reversed_at']!r}"
        )
        assert program_cash_total(program_parties()) == cash_before, (
            "a refused reversal must move no cash at all"
        )

        rows, meta = validate_paginated(api_client.list_certificate_transfers(
            ADMIN, params={"certificate_id": scenario["certificate"]["id"]}
        ))
        assert meta["total_count"] == 3, (
            "the chain of title holds ISSUANCE, PRIVATE_SALE and RETIREMENT only, found "
            f"{meta['total_count']}"
        )
        assert [row["transfer_type"] for row in rows] == [
            "ISSUANCE", "PRIVATE_SALE", "RETIREMENT"
        ], f"no REVERSAL row may be appended by a refused reversal, got {rows!r}"


class TestCertificateUnitCeilings:
    """A split must leave a unit behind; a retirement may take everything."""

    def test_a_split_that_would_take_every_unit_is_refused(self):
        """22 of 22 available units is one unit too many for a split.

        PRD §3.6: "And the split must leave at least one unencumbered unit on the parent:
        `units` must be strictly less than the parent's available quantity, so a split
        that would take everything is rejected with
        `ERR_SPLIT_EXCEEDS_AVAILABLE_UNITS`."

        PRD §2.10: "38. A split leaves at least one unencumbered unit on the parent;
        otherwise `ERR_SPLIT_EXCEEDS_AVAILABLE_UNITS` (422)."

        Design: Corner/errors/certificate_unit_guards_separate_the_split_and_retire_ceilings
        """
        scenario = setup_certified_severance(units=22, clock=CLOCK)
        certificate = fetch_certificate(scenario["certificate"]["id"])
        holder = make_landowner_headers(scenario["landowner"]["id"])
        assert certificate["units_remaining"] - certificate["units_encumbered"] == 22, (
            "all 22 units must be available for the ceiling comparison to be about 22"
        )

        response = api_client.split_certificate(
            certificate["id"],
            split_certificate_payload(22, certificate["version"]),
            holder,
        )
        validate_error(response, ApiErrorId.ERR_SPLIT_EXCEEDS_AVAILABLE_UNITS.value)

        after = fetch_certificate(certificate["id"])
        assert after["units_split_out"] == 0, (
            f"a refused split moves nothing out, got {after['units_split_out']}"
        )
        assert after["split_count"] == 0, (
            f"a refused split mints no child, got split_count {after['split_count']}"
        )
        _, meta = validate_paginated(api_client.list_certificates(
            ADMIN, params={"parent_certificate_id": certificate["id"]}
        ))
        assert meta["total_count"] == 0, (
            f"a refused split leaves no child certificate, found {meta['total_count']}"
        )

    def test_a_retirement_beyond_the_available_balance_is_refused(self):
        """25 of 22 available units exceeds the retirement ceiling.

        PRD §3.6: "Retirement requires `lifecycle_status` of `ISSUED` or
        `PARTIALLY_REDEEMED`, `market_status` of `HELD`, and `units` no greater than the
        certificate's available quantity — a request beyond that is rejected with
        `ERR_INSUFFICIENT_CERTIFICATE_UNITS`."

        PRD §2.10: "39. The requested units are available on the certificate; otherwise
        `ERR_INSUFFICIENT_CERTIFICATE_UNITS` (422). Applies to transaction proposal,
        redemption allocation, and certificate retirement."

        Design: Corner/errors/certificate_unit_guards_separate_the_split_and_retire_ceilings
        """
        scenario = setup_certified_severance(units=22, clock=CLOCK)
        certificate = fetch_certificate(scenario["certificate"]["id"])
        holder = make_landowner_headers(scenario["landowner"]["id"])

        response = api_client.retire_certificate_units(
            certificate["id"],
            retire_certificate_payload(25, reason="over-large retirement attempt"),
            holder,
        )
        validate_error(response, ApiErrorId.ERR_INSUFFICIENT_CERTIFICATE_UNITS.value)

        after = fetch_certificate(certificate["id"])
        assert after["units_retired"] == 0, (
            f"a refused retirement extinguishes nothing, got {after['units_retired']}"
        )
        assert after["lifecycle_status"] == "ISSUED", (
            f"a refused retirement advances no lifecycle, got {after['lifecycle_status']}"
        )

    def test_neither_refusal_bumps_the_certificate_version(self):
        """The version observed before both refusals still satisfies the split's version gate.

        PRD §2.3: "`version` is an integer that starts at 1 when the row is created and
        increases by exactly one on every mutation of that row, including mutations
        reached through a cascade rather than through a direct request."

        PRD §2.8: "Splitting a certificate requires `expected_certificate_version`,
        carrying the client's last observed `version` of that `Certificate`."

        PRD §3.6: "The child certificate is minted with `parent_certificate_id` pointing
        at the parent, with `conservation_easement_id`, `origin_sending_area_id` and
        `origin_neighborhood_code` copied down the lineage unchanged, with
        `holder_party_id` equal to the parent's holder, with `units_face` and
        `units_remaining` both equal to the requested `units`, with `generation` one
        higher than the parent's `generation`, with `split_count` at 0, with
        `lifecycle_status` of `ISSUED` and `market_status` of `HELD`, and with
        `issued_at` at the current logical clock."

        PRD §3.6: "On the parent, `units_split_out` grows by `units` and `units_remaining`
        is recomputed, but `lifecycle_status` and `market_status` are both left exactly
        where they were: a split is a lineage mutation, not a lifecycle advance, which is
        why the parent's rights dimension can stay `ISSUED` across an arbitrary number of
        splits."

        Design: Corner/errors/certificate_unit_guards_separate_the_split_and_retire_ceilings
        """
        scenario = setup_certified_severance(units=22, clock=CLOCK)
        certificate = fetch_certificate(scenario["certificate"]["id"])
        holder = make_landowner_headers(scenario["landowner"]["id"])
        observed_version = certificate["version"]

        validate_error(
            api_client.split_certificate(
                certificate["id"], split_certificate_payload(22, observed_version), holder
            ),
            ApiErrorId.ERR_SPLIT_EXCEEDS_AVAILABLE_UNITS.value,
        )
        validate_error(
            api_client.retire_certificate_units(
                certificate["id"], retire_certificate_payload(25), holder
            ),
            ApiErrorId.ERR_INSUFFICIENT_CERTIFICATE_UNITS.value,
        )
        assert fetch_certificate(certificate["id"])["version"] == observed_version, (
            "two refused writes must leave the certificate version where it was"
        )

        child = get_success_data(api_client.split_certificate(
            certificate["id"], split_certificate_payload(21, observed_version), holder
        ))
        assert_certificate(child)
        assert child["units_face"] == 21, (
            f"the child carries the requested units, got {child['units_face']}"
        )
        assert child["units_remaining"] == 21, (
            f"the child's units are all available, got {child['units_remaining']}"
        )
        assert child["generation"] == certificate["generation"] + 1, (
            f"the child sits one generation below its parent, got {child['generation']}"
        )
        assert child["parent_certificate_id"] == certificate["id"], (
            f"the child names its parent, got {child['parent_certificate_id']!r}"
        )

        parent = fetch_certificate(certificate["id"])
        assert parent["units_split_out"] == 21, (
            f"the parent moved 21 units out, got {parent['units_split_out']}"
        )
        assert parent["units_remaining"] == 1, (
            f"the parent keeps the one unit the ceiling protects, got "
            f"{parent['units_remaining']}"
        )
        assert parent["split_count"] == 1, (
            f"the parent counts one split, got {parent['split_count']}"
        )
        assert parent["lifecycle_status"] == "ISSUED", (
            f"a split is no lifecycle advance, got {parent['lifecycle_status']}"
        )


class TestCureVerificationOnAClosedInspection:
    """The same call, two codes, decided by who is calling."""

    def test_a_compliant_inspection_closes_on_creation_and_cannot_be_cured(self):
        """There is nothing to verify on an inspection that never entered CURE_PENDING.

        PRD §3.9: "A finding of `COMPLIANT` records `severity_score` as 0.00, leaves
        `cure_deadline` unset, and opens the inspection directly in `CLOSED`."

        PRD §3.9: "The inspection must be in `CURE_PENDING` for either outcome, otherwise
        `ERR_INSPECTION_NOT_CURABLE`, and segregation of duties applies: the verifying
        user must differ from the `inspector_user_id` who recorded the finding, otherwise
        `ERR_SEGREGATION_OF_DUTIES`."

        PRD §2.10: "21. The inspection is `CURE_PENDING` before a cure verification;
        otherwise `ERR_INSPECTION_NOT_CURABLE` (409)."

        Design: Corner/errors/cure_verification_on_a_closed_compliant_inspection_is_rejected
        """
        scenario = setup_certified_severance(units=22, clock=CLOCK)
        inspection = record_inspection(
            scenario["easement"]["id"], "2026-08-10", "COMPLIANT", 0.00, MONITOR_USER_ID,
            note="annual walkover, no issues",
        )
        assert_monitoring_inspection(inspection)
        assert inspection["status"] == "CLOSED", (
            f"a COMPLIANT finding closes on creation, got {inspection['status']}"
        )
        assert float(inspection["severity_score"]) == 0.00, (
            f"a COMPLIANT finding scores 0.00, got {inspection['severity_score']}"
        )
        assert inspection["cure_deadline"] is None, (
            f"a COMPLIANT finding leaves no cure deadline, got {inspection['cure_deadline']!r}"
        )
        assert inspection["inspector_user_id"] == MONITOR_USER_ID, (
            f"the recording monitor is stored, got {inspection['inspector_user_id']!r}"
        )

        response = api_client.verify_cure(
            inspection["id"], cure_verification_payload("CURED", verification_note="nothing to cure"),
            make_monitor_headers(MONITOR_USER_ID_ALT),
        )
        validate_error(response, ApiErrorId.ERR_INSPECTION_NOT_CURABLE.value)

        after = fetch_inspection(inspection["id"])
        assert after["cure_verified_at"] is None, (
            f"a refused verification stamps nothing, got {after['cure_verified_at']!r}"
        )
        assert after["cure_verified_by_user_id"] is None, (
            f"a refused verification records no verifier, got "
            f"{after['cure_verified_by_user_id']!r}"
        )
        easement = fetch_easement(scenario["easement"]["id"])
        assert easement["compliance_status"] == "COMPLIANT", (
            f"a compliant walkover leaves the easement compliant, got "
            f"{easement['compliance_status']}"
        )
        assert easement["prior_violation_count"] == 0, (
            f"no violation was ever noticed, got {easement['prior_violation_count']}"
        )
        assert fetch_certificate(scenario["certificate"]["id"])["market_status"] == "HELD", (
            "no freeze and no thaw may follow a compliant inspection"
        )

    def test_the_recording_inspector_is_refused_before_the_state_of_the_inspection(self):
        """Segregation of duties sits above the state rung, so mon-1 gets the 403.

        PRD §2.1: "Segregation of duties, rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP
        403), requires that the `X-User-ID` certifying a severance application differ from
        the `decided_by_user_id` that recorded its approval, and that the `X-User-ID`
        verifying a cure differ from the `inspector_user_id` that recorded the
        inspection."

        PRD §2.10: "the first check that fails decides the response, and no later check
        is consulted"

        PRD §2.10: "8. **Segregation of duties** — as described in §2.1; otherwise
        `ERR_SEGREGATION_OF_DUTIES` (403). Applies to severance certification and cure
        verification."

        PRD §2.10: "21. The inspection is `CURE_PENDING` before a cure verification;
        otherwise `ERR_INSPECTION_NOT_CURABLE` (409)."

        Design: Corner/errors/cure_verification_on_a_closed_compliant_inspection_is_rejected
        """
        scenario = setup_certified_severance(units=22, clock=CLOCK)
        inspection = record_inspection(
            scenario["easement"]["id"], "2026-08-10", "COMPLIANT", 0.00, MONITOR_USER_ID,
            note="annual walkover, no issues",
        )
        observed_version = inspection["version"]

        response = api_client.verify_cure(
            inspection["id"], cure_verification_payload("CURED", verification_note="nothing to cure"),
            make_monitor_headers(MONITOR_USER_ID),
        )
        validate_error(response, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)

        after = fetch_inspection(inspection["id"])
        assert after["version"] == observed_version, (
            "a refused verification mutates nothing, so the version must stand at "
            f"{observed_version}, got {after['version']}"
        )
        assert after["status"] == "CLOSED", (
            f"the inspection stays closed, got {after['status']}"
        )


class TestEvaluationPeriodGeometry:
    """Period geometry alone decides between a refusal, a restatement and a coexistence."""

    def test_a_partially_overlapping_period_is_refused(self):
        """A window that straddles the incumbent's end date cannot be computed.

        PRD §3.9: "The window is inclusive at both ends and compared at date
        granularity."

        PRD §3.9: "Overlap with existing evaluations is constrained in a specific way: no
        other `COMPUTED` evaluation may partially overlap the requested window, and a
        partial overlap is rejected with `ERR_EVALUATION_PERIOD_OVERLAP` — but an
        exact-match period is allowed, and computing it moves the earlier evaluation to
        `SUPERSEDED`, which is how the program restates a period after corrections."

        PRD §2.10: "31. A new evaluation period does not partially overlap an existing
        `COMPUTED` evaluation period; otherwise `ERR_EVALUATION_PERIOD_OVERLAP` (409)."

        Design: Corner/errors/a_partially_overlapping_evaluation_period_is_rejected_while_an_identical_one_supersedes
        """
        set_clock(CLOCK)
        incumbent = compute_evaluation("2026-01-01", "2026-12-31", "ACREAGE_WEIGHTED")
        assert_program_evaluation(incumbent)
        assert incumbent["status"] == "COMPUTED", (
            f"an evaluation starts COMPUTED, got {incumbent['status']}"
        )

        response = api_client.create_evaluation(
            create_evaluation_payload("2026-06-01", "2027-06-01", "PARCEL_COUNT_WEIGHTED"),
            ADMIN,
        )
        validate_error(response, ApiErrorId.ERR_EVALUATION_PERIOD_OVERLAP.value)

        _, meta = validate_paginated(api_client.list_evaluations(ADMIN))
        assert meta["total_count"] == 1, (
            f"a refused evaluation creates no row, found {meta['total_count']}"
        )
        assert _fetch_evaluation(incumbent["id"])["status"] == "COMPUTED", (
            "a refused evaluation leaves the incumbent COMPUTED"
        )

    def test_an_identical_period_is_accepted_and_supersedes_the_incumbent(self):
        """The exact-match restatement is the one overlap the program allows.

        PRD §3.9: "Overlap with existing evaluations is constrained in a specific way: no
        other `COMPUTED` evaluation may partially overlap the requested window, and a
        partial overlap is rejected with `ERR_EVALUATION_PERIOD_OVERLAP` — but an
        exact-match period is allowed, and computing it moves the earlier evaluation to
        `SUPERSEDED`, which is how the program restates a period after corrections."

        Design: Corner/errors/a_partially_overlapping_evaluation_period_is_rejected_while_an_identical_one_supersedes
        """
        set_clock(CLOCK)
        incumbent = compute_evaluation("2026-01-01", "2026-12-31", "ACREAGE_WEIGHTED")
        restatement = compute_evaluation("2026-01-01", "2026-12-31", "PARCEL_COUNT_WEIGHTED")
        assert_program_evaluation(restatement)

        assert _fetch_evaluation(incumbent["id"])["status"] == "SUPERSEDED", (
            "computing an identical period restates it, moving the earlier row to SUPERSEDED"
        )
        assert _fetch_evaluation(restatement["id"])["status"] == "COMPUTED", (
            "the restatement itself stays COMPUTED"
        )
        assert_same_date(restatement["period_start"], "2026-01-01", "period_start")
        assert_same_date(restatement["period_end"], "2026-12-31", "period_end")

    def test_a_disjoint_period_coexists_with_the_incumbent(self):
        """Non-overlapping windows are simply two computed evaluations.

        PRD §3.9: "Overlap with existing evaluations is constrained in a specific way: no
        other `COMPUTED` evaluation may partially overlap the requested window, and a
        partial overlap is rejected with `ERR_EVALUATION_PERIOD_OVERLAP` — but an
        exact-match period is allowed, and computing it moves the earlier evaluation to
        `SUPERSEDED`, which is how the program restates a period after corrections."

        PRD §3.9: "Evaluations start in `COMPUTED` and can be listed with `status` and
        `equity_weighting` filters plus `limit` and `offset`."

        Design: Corner/errors/a_partially_overlapping_evaluation_period_is_rejected_while_an_identical_one_supersedes
        """
        set_clock(CLOCK)
        first = compute_evaluation("2026-01-01", "2026-12-31", "ACREAGE_WEIGHTED")
        second = compute_evaluation("2027-01-01", "2027-12-31", "ACREAGE_WEIGHTED")

        assert _fetch_evaluation(first["id"])["status"] == "COMPUTED", (
            "a disjoint period supersedes nothing"
        )
        assert _fetch_evaluation(second["id"])["status"] == "COMPUTED", (
            f"the disjoint evaluation is computed, got {second['status']}"
        )
        _, meta = validate_paginated(api_client.list_evaluations(
            ADMIN, params={"status": "COMPUTED"}
        ))
        assert meta["total_count"] == 2, (
            f"both disjoint evaluations remain COMPUTED, found {meta['total_count']}"
        )

    def test_an_empty_program_reports_zero_where_a_denominator_is_zero(self):
        """No receiving areas and no easements means division by zero, reported as 0.00.

        PRD §3.9: "`absorption_pct` is the sum of `absorbed_units` divided by the sum of
        `absorption_cap_units` across every receiving area whose `status` is `ACTIVE` or
        `SUSPENDED`, as a percentage rounded half up to two decimal places, and reports
        0.00 rather than erroring when the denominator is zero; `DRAFT` areas never enter
        that denominator, and the figure is a program-wide snapshot rather than a
        window-scoped one."

        PRD §3.9: "Both are percentages rounded half up to two decimal places, and both
        report 0.00 when their denominator is zero."

        Design: Corner/errors/a_partially_overlapping_evaluation_period_is_rejected_while_an_identical_one_supersedes
        """
        set_clock(CLOCK)
        acreage = compute_evaluation("2026-01-01", "2026-12-31", "ACREAGE_WEIGHTED")
        assert float(acreage["absorption_pct"]) == 0.00, (
            f"an empty absorption denominator reports 0.00, got {acreage['absorption_pct']}"
        )
        assert float(acreage["equity_index"]) == 0.00, (
            f"an empty equity denominator reports 0.00, got {acreage['equity_index']}"
        )

        counted = compute_evaluation("2026-01-01", "2026-12-31", "PARCEL_COUNT_WEIGHTED")
        assert float(counted["equity_index"]) == 0.00, (
            "the count-weighted variant reports 0.00 on the same empty program, got "
            f"{counted['equity_index']}"
        )


class TestReceivingSideIntakeAndFinalizationGuards:
    """A DRAFT area takes no filings; an ACTIVE one defers the backing test to finalization."""

    def test_a_draft_receiving_area_accepts_no_filing(self):
        """Designation alone does not open an area to development applications.

        PRD §3.8: "A `Developer` files a receiving-site application naming
        `developer_party_id`, `receiving_area_id`, `site_acres`, and
        `requested_bonus_units`. The named area must be `ACTIVE`, otherwise
        `ERR_RECEIVING_AREA_NOT_ACTIVE`, and the filing party must be `ACTIVE` and must be
        the acting developer."

        PRD §3.2: "A new receiving area opens in `status` `DRAFT` with `absorbed_units` and
        `reserved_units` at 0, and activation moves it `DRAFT → ACTIVE` with a `version`
        increment, again rejecting a non-`DRAFT` area with `ERR_AREA_NOT_DRAFT`."

        PRD §2.10: "27. The `ReceivingArea` has `status` of `ACTIVE`; otherwise
        `ERR_RECEIVING_AREA_NOT_ACTIVE` (409). Applies to receiving-site filing, redemption
        allocation, and finalization."

        Design: Corner/errors/receiving_side_intake_and_finalization_guards_each_report_their_own_code
        """
        set_clock(CLOCK)
        developer = register_developer(neighborhood_code="NB-CORE")
        draft_area = designate_receiving_area(
            neighborhood_code="NB-SOUTH",
            base_density_units_per_acre=4.00,
            max_bonus_pct=0.35,
            absorption_cap_units=500,
            design_review_required=False,
        )
        assert draft_area["status"] == "DRAFT", (
            f"a designated area opens in DRAFT, got {draft_area['status']}"
        )

        response = api_client.create_receiving_site_application(
            create_receiving_site_application_payload(
                developer["id"], draft_area["id"], 2.50, 20
            ),
            make_developer_headers(developer["id"]),
        )
        validate_error(response, ApiErrorId.ERR_RECEIVING_AREA_NOT_ACTIVE.value)

        _, meta = validate_paginated(api_client.list_receiving_site_applications(
            ADMIN, params={"receiving_area_id": draft_area["id"]}
        ))
        assert meta["total_count"] == 0, (
            f"the refused filing creates no application, found {meta['total_count']}"
        )

    def test_finalizing_an_application_with_no_backing_at_all_is_refused(self):
        """An unbacked application sits legitimately in DESIGN_APPROVED and fails at the gate.

        PRD §3.8: "First a site tier factor is chosen from `site_acres`: a site of at least
        10.00 acres takes 1.00, a site of at least 3.00 but under 10.00 acres takes 0.90,
        and anything smaller takes 0.75."

        PRD §3.8: "Second, `base_units` is `site_acres` multiplied by the area's
        `base_density_units_per_acre`, floored to a whole number."

        PRD §3.8: "Third, `max_bonus_units` is the already-floored `base_units` multiplied
        by the area's `max_bonus_pct` and then by the tier factor, floored again."

        PRD §3.8: "`required_backing_units` is then the lesser of `requested_bonus_units`
        and `max_bonus_units` — a developer who asks for more density than the area can
        grant is not rejected at intake, but is only ever required to back, and can only
        ever receive, the area's maximum."

        PRD §3.8: "When the flag is false, it starts `SUBMITTED → DESIGN_APPROVED` and
        skips the board entirely, with `design_review_round` left at 0 and
        `design_reviewed_by_user_id` left unset."

        PRD §3.8: "Sufficiency is checked second: `backed_units` plus
        `pending_backed_units` must be at least `required_backing_units`, otherwise
        `ERR_BACKING_INSUFFICIENT`."

        PRD §2.10: "40. Backing is sufficient at finalization; otherwise
        `ERR_BACKING_INSUFFICIENT` (409)."

        Design: Corner/errors/receiving_side_intake_and_finalization_guards_each_report_their_own_code
        """
        set_clock(CLOCK)
        developer = register_developer(neighborhood_code="NB-CORE")
        area = create_active_receiving_area(
            neighborhood_code="NB-CORE",
            base_density_units_per_acre=4.00,
            max_bonus_pct=0.35,
            absorption_cap_units=500,
            design_review_required=False,
            eligible_sending_area_codes=[],
        )
        application = file_receiving_site_application(
            developer["id"], area["id"], site_acres=2.50, requested_bonus_units=20
        )
        assert_receiving_site_application(application)
        assert application["status"] == "DESIGN_APPROVED", (
            f"an area that requires no design review approves at intake, got "
            f"{application['status']}"
        )
        assert application["base_units"] == 10, (
            f"2.50 acres at 4.00 units per acre floors to 10, got {application['base_units']}"
        )
        assert application["max_bonus_units"] == 2, (
            "10 base units at 0.35 and the 0.75 small-site factor floors to 2, got "
            f"{application['max_bonus_units']}"
        )
        assert application["required_backing_units"] == 2, (
            "a 20-unit request is capped by the area's maximum of 2, got "
            f"{application['required_backing_units']}"
        )
        assert application["provisional_bonus_units"] == 1, (
            f"half of 2 floored is 1, got {application['provisional_bonus_units']}"
        )
        assert application["backed_units"] == 0, (
            f"nothing is backed yet, got {application['backed_units']}"
        )
        assert application["pending_backed_units"] == 0, (
            f"nothing is pending either, got {application['pending_backed_units']}"
        )

        response = api_client.finalize_receiving_site_application(
            application["id"], make_developer_headers(developer["id"]),
            {"finalization_note": "attempting to finalize with no backing"},
        )
        validate_error(response, ApiErrorId.ERR_BACKING_INSUFFICIENT.value)

        after = fetch_receiving_site_application(application["id"])
        assert after["status"] == "DESIGN_APPROVED", (
            f"the refusal does not push the application onward, got {after['status']}"
        )
        assert after["finalized_at"] is None, (
            f"a refused finalization stamps nothing, got {after['finalized_at']!r}"
        )
        assert after["allocated_bonus_units"] == 0, (
            f"a refused finalization grants no bonus, got {after['allocated_bonus_units']}"
        )
        area_after = fetch_receiving_area(area["id"])
        assert area_after["absorbed_units"] == 0, (
            f"nothing was absorbed, got {area_after['absorbed_units']}"
        )
        assert area_after["reserved_units"] == 0, (
            f"nothing was reserved, got {area_after['reserved_units']}"
        )
        assert area_after["status"] == "ACTIVE", (
            f"the area stays ACTIVE, got {area_after['status']}"
        )


def _application_awaiting_revisions():
    """A 12.00-acre application in a board-reviewed area, sized to a 16-unit ceiling on a
    10-unit request, that the board has sent back for revisions."""
    set_clock(CLOCK)
    developer = register_developer(neighborhood_code="NB-CORE")
    area = create_active_receiving_area(
        neighborhood_code="NB-CORE",
        base_density_units_per_acre=4.00,
        max_bonus_pct=0.35,
        absorption_cap_units=500,
        design_review_required=True,
        eligible_sending_area_codes=[],
    )
    application = file_receiving_site_application(
        developer["id"], area["id"], site_acres=12.00, requested_bonus_units=10
    )
    assert application["status"] == "DESIGN_REVIEW", (
        f"a board-reviewed area routes intake to DESIGN_REVIEW, got {application['status']}"
    )
    assert application["base_units"] == 48, (
        f"12.00 acres at 4.00 units per acre is 48, got {application['base_units']}"
    )
    assert application["max_bonus_units"] == 16, (
        f"48 base units at 0.35 and the 1.00 large-site factor floors to 16, got "
        f"{application['max_bonus_units']}"
    )
    assert application["required_backing_units"] == 10, (
        f"a 10-unit request under a 16-unit ceiling requires 10, got "
        f"{application['required_backing_units']}"
    )
    assert application["provisional_bonus_units"] == 8, (
        f"half of 16 floored is 8, and 8 is below the 10 requested, got "
        f"{application['provisional_bonus_units']}"
    )
    returned = design_decision(
        application["id"], "REQUIRE_REVISIONS", review_note="massing and setbacks"
    )
    assert returned["status"] == "REVISIONS_REQUIRED", (
        f"REQUIRE_REVISIONS parks the application for revision, got {returned['status']}"
    )
    return developer, area, returned


class TestDesignResubmissionCeiling:
    """Intake tolerates an over-ask; resubmission does not."""

    def test_a_restated_request_above_the_area_maximum_is_refused(self):
        """The ceiling the intake sizing merely capped is enforced outright on resubmission.

        PRD §3.8: "`required_backing_units` is then the lesser of `requested_bonus_units`
        and `max_bonus_units` — a developer who asks for more density than the area can
        grant is not rejected at intake, but is only ever required to back, and can only
        ever receive, the area's maximum."

        PRD §3.8: "Unlike intake, resubmission enforces the ceiling directly: a restated
        `requested_bonus_units` above `max_bonus_units` is rejected with
        `ERR_BONUS_EXCEEDS_MAX`."

        PRD §2.10: "37. `requested_bonus_units` does not exceed the recomputed
        `max_bonus_units`; otherwise `ERR_BONUS_EXCEEDS_MAX` (422). Applies to design
        resubmission."

        Design: Corner/errors/a_resubmitted_design_above_the_bonus_ceiling_is_rejected
        """
        developer, _area, application = _application_awaiting_revisions()
        before = fetch_receiving_site_application(application["id"])

        response = api_client.resubmit_design(
            application["id"],
            resubmit_design_payload(17, revision_note="asking for one more than the ceiling"),
            make_developer_headers(developer["id"]),
        )
        validate_error(response, ApiErrorId.ERR_BONUS_EXCEEDS_MAX.value)

        after = fetch_receiving_site_application(application["id"])
        assert after["status"] == "REVISIONS_REQUIRED", (
            f"the refused resubmission leaves the design cycle open, got {after['status']}"
        )
        assert after["requested_bonus_units"] == 10, (
            f"the refused figure never replaces the standing request, got "
            f"{after['requested_bonus_units']}"
        )
        assert after["required_backing_units"] == 10, (
            f"nothing is resized by a refusal, got {after['required_backing_units']}"
        )
        assert after["provisional_bonus_units"] == 8, (
            f"nothing is resized by a refusal, got {after['provisional_bonus_units']}"
        )
        assert after["design_review_round"] == before["design_review_round"], (
            f"only a valid resubmission advances the round, got "
            f"{after['design_review_round']} from {before['design_review_round']}"
        )
        assert after["version"] == before["version"], (
            f"the refusal writes nothing, so the version holds at {before['version']}, "
            f"got {after['version']}"
        )

    def test_a_restated_request_exactly_at_the_area_maximum_reopens_review(self):
        """The comparison is inclusive: the ceiling itself is a legal restatement.

        PRD §3.8: "Unlike intake, resubmission enforces the ceiling directly: a restated
        `requested_bonus_units` above `max_bonus_units` is rejected with
        `ERR_BONUS_EXCEEDS_MAX`. A valid resubmission increments `design_review_round`,
        replaces `requested_bonus_units`, re-runs the provisional sizing so
        `required_backing_units` and `provisional_bonus_units` are both restated, moves the
        application `REVISIONS_REQUIRED → DESIGN_REVIEW`, and increments `version`."

        PRD §3.8: "The provisional variant, used at intake and again on every design
        resubmission, writes `provisional_bonus_units` as the lesser of
        `requested_bonus_units` and half of `max_bonus_units` floored — a release fraction
        of one half."

        Design: Corner/errors/a_resubmitted_design_above_the_bonus_ceiling_is_rejected
        """
        developer, _area, application = _application_awaiting_revisions()
        before = fetch_receiving_site_application(application["id"])

        restated = resubmit_design(
            application["id"], developer["id"], 16, revision_note="restated to the ceiling"
        )
        assert_receiving_site_application(restated)
        assert restated["status"] == "DESIGN_REVIEW", (
            f"a valid resubmission returns the application to the board, got "
            f"{restated['status']}"
        )
        assert restated["design_review_round"] == before["design_review_round"] + 1, (
            f"the round advances by one from {before['design_review_round']}, got "
            f"{restated['design_review_round']}"
        )
        assert restated["requested_bonus_units"] == 16, (
            f"the restated figure replaces the old one, got {restated['requested_bonus_units']}"
        )
        assert restated["max_bonus_units"] == 16, (
            f"the area's ceiling is unaffected by the request, got "
            f"{restated['max_bonus_units']}"
        )
        assert restated["required_backing_units"] == 16, (
            f"16 requested against a 16-unit ceiling requires 16, got "
            f"{restated['required_backing_units']}"
        )
        assert restated["provisional_bonus_units"] == 8, (
            f"half of 16 floored is still 8, got {restated['provisional_bonus_units']}"
        )
        assert restated["version"] > before["version"], (
            f"a valid resubmission increments the version past {before['version']}, got "
            f"{restated['version']}"
        )


class TestFrozenBackingPoolGuards:
    """One frozen source easement out of two: the surviving backing is enough for the
    sufficiency gate and still not enough to finalize."""

    def test_finalization_is_refused_for_compliance_even_though_the_backing_suffices(self):
        """The compliance gate reaches held rows, so an over-collateralized application stalls.

        PRD §3.9: "Third — caused by the second — every redemption in `ALLOCATED` on a
        just-frozen certificate moves `ALLOCATED → HELD_PENDING_COMPLIANCE`; its units stay
        inside the certificate's `units_encumbered` and the area's `reserved_units`, but
        they leave the application's `pending_backed_units`, because held backing no longer
        counts as backing."

        PRD §3.9: "An application whose backing survives the recompute stays
        `DESIGN_APPROVED`, so link four fires selectively."

        PRD §3.8: "Three gates then apply in a fixed order. Compliance is checked first,
        before any capacity arithmetic: every source easement behind a redemption in
        `ALLOCATED` or `HELD_PENDING_COMPLIANCE` must be `COMPLIANT` or `CURED`, otherwise
        `ERR_EASEMENT_NONCOMPLIANT`. Sufficiency is checked second: `backed_units` plus
        `pending_backed_units` must be at least `required_backing_units`, otherwise
        `ERR_BACKING_INSUFFICIENT`."

        PRD §2.10: "25. **Application compliance** — every source `ConservationEasement`
        behind one of the application's redemptions in status `ALLOCATED` or
        `HELD_PENDING_COMPLIANCE` has `compliance_status` of either `COMPLIANT` or `CURED`;
        otherwise `ERR_EASEMENT_NONCOMPLIANT` (409). Applies to finalization, ahead of
        every constraint check on that endpoint."

        Design: Corner/errors/finalization_and_redemption_guards_on_a_partly_frozen_backing_pool
        """
        pool = _partly_frozen_backing_pool()
        assert pool["certificate_a"]["market_status"] == "FROZEN", (
            f"the violation freezes the first certificate, got "
            f"{pool['certificate_a']['market_status']}"
        )
        assert pool["redemption_a"]["status"] == "HELD_PENDING_COMPLIANCE", (
            f"its redemption is held, not released, got {pool['redemption_a']['status']}"
        )
        assert pool["redemption_b"]["status"] == "ALLOCATED", (
            f"the clean redemption is untouched, got {pool['redemption_b']['status']}"
        )
        rsa = pool["rsa"]
        assert rsa["status"] == "DESIGN_APPROVED", (
            f"the surviving 2 units still meet the requirement, so the application does "
            f"not fall to BACKING_DEFICIENT, got {rsa['status']}"
        )
        assert rsa["required_backing_units"] == 2, (
            f"a 20-unit request on this area requires 2, got {rsa['required_backing_units']}"
        )
        assert rsa["pending_backed_units"] == 2, (
            f"only the unheld redemption counts, got {rsa['pending_backed_units']}"
        )
        assert rsa["backed_units"] == 0, (
            f"nothing is confirmed before finalization, got {rsa['backed_units']}"
        )

        response = api_client.finalize_receiving_site_application(
            rsa["id"], make_developer_headers(pool["developer"]["id"]),
            {"finalization_note": "one source easement is out of compliance"},
        )
        validate_error(response, ApiErrorId.ERR_EASEMENT_NONCOMPLIANT.value)

        after = fetch_receiving_site_application(rsa["id"])
        assert after["status"] == "DESIGN_APPROVED", (
            f"the refusal leaves the application where it stood, got {after['status']}"
        )
        assert after["finalized_at"] is None, (
            f"a refused finalization stamps nothing, got {after['finalized_at']!r}"
        )
        assert after["allocated_bonus_units"] == 0, (
            f"a refused finalization grants no bonus, got {after['allocated_bonus_units']}"
        )
        core_after = fetch_receiving_area(pool["core_area"]["id"])
        assert core_after["absorbed_units"] == 0, (
            f"nothing is absorbed by a refused finalization, got "
            f"{core_after['absorbed_units']}"
        )
        assert core_after["reserved_units"] == 3, (
            f"all 3 committed units — held and allocated alike — stay reserved, got "
            f"{core_after['reserved_units']}"
        )

    def test_a_certificate_from_an_unlisted_sending_area_cannot_back_the_application(self):
        """A non-empty whitelist is a closed list, and the certificate's origin decides.

        PRD §3.8: "Pairing is checked next: when the area's `eligible_sending_area_codes`
        list is non-empty, the certificate's origin sending area code must appear in it,
        otherwise `ERR_SENDING_RECEIVING_PAIR_NOT_ELIGIBLE`; an empty list means every
        sending area is eligible."

        PRD §2.10: "28. When the receiving area's `eligible_sending_area_codes` list is
        non-empty, the certificate's origin sending area `code` appears in it; an empty list
        means every sending area is eligible. A violation is
        `ERR_SENDING_RECEIVING_PAIR_NOT_ELIGIBLE` (422). Applies to redemption allocation."

        Design: Corner/errors/finalization_and_redemption_guards_on_a_partly_frozen_backing_pool
        """
        pool = _partly_frozen_backing_pool()
        north_rsa = pool["north_rsa"]
        assert pool["north_area"]["eligible_sending_area_codes"] == ["SA-WEST"], (
            f"the second area admits exactly one foreign code, got "
            f"{pool['north_area']['eligible_sending_area_codes']}"
        )
        assert pool["certificate_b"]["market_status"] == "HELD", (
            f"the certificate offered as backing is itself unfrozen, got "
            f"{pool['certificate_b']['market_status']}"
        )

        response = api_client.allocate_redemption(
            north_rsa["id"],
            allocate_redemption_payload(
                pool["certificate_b"]["id"], 1, north_rsa["version"]
            ),
            make_developer_headers(pool["developer"]["id"]),
        )
        validate_error(response, ApiErrorId.ERR_SENDING_RECEIVING_PAIR_NOT_ELIGIBLE.value)

        _, meta = validate_paginated(api_client.list_certificate_redemptions(
            ADMIN, params={"receiving_site_application_id": north_rsa["id"]}
        ))
        assert meta["total_count"] == 0, (
            f"the refused allocation creates no redemption, found {meta['total_count']}"
        )
        after = fetch_receiving_site_application(north_rsa["id"])
        assert after["version"] == north_rsa["version"], (
            f"the refusal writes nothing, so the version holds at "
            f"{north_rsa['version']}, got {after['version']}"
        )
        assert after["pending_backed_units"] == 0, (
            f"the second application is still unbacked, got {after['pending_backed_units']}"
        )

    def test_a_held_redemption_releases_once_and_only_once(self):
        """Release accepts a held row, and the second attempt has nothing left to release.

        PRD §3.8: "A redemption in `ALLOCATED` or `HELD_PENDING_COMPLIANCE` may be
        released, with an optional `reason`, by the application's own developer or by a
        `ProgramAdministrator`. The redemption must be in one of those two states and its
        application must not be `FINALIZED`, otherwise `ERR_REDEMPTION_NOT_RELEASABLE`.
        Release sets `released_at`, reduces the certificate's `units_encumbered` by `units`
        and the area's `reserved_units` by `units`, recomputes `pending_backed_units`, and
        increments the redemption's `version`."

        PRD §2.10: "17. The redemption is `ALLOCATED` or `HELD_PENDING_COMPLIANCE` and its
        application is not `FINALIZED`; otherwise `ERR_REDEMPTION_NOT_RELEASABLE` (409).
        Applies to redemption release."

        Design: Corner/errors/finalization_and_redemption_guards_on_a_partly_frozen_backing_pool
        """
        pool = _partly_frozen_backing_pool()
        developer_headers = make_developer_headers(pool["developer"]["id"])

        released = release_redemption(
            pool["redemption_a"]["id"], actor_headers=developer_headers,
            reason="swapping out the frozen backing",
        )
        assert_certificate_redemption(released)
        assert released["status"] == "RELEASED", (
            f"a held redemption releases, got {released['status']}"
        )
        assert_same_instant(released["released_at"], CLOCK)
        certificate_a = fetch_certificate(pool["certificate_a"]["id"])
        assert certificate_a["units_encumbered"] == 0, (
            f"the released unit leaves the encumbrance, got "
            f"{certificate_a['units_encumbered']}"
        )
        assert certificate_a["market_status"] == "FROZEN", (
            f"releasing backing does not unfreeze the certificate, got "
            f"{certificate_a['market_status']}"
        )
        core_after = fetch_receiving_area(pool["core_area"]["id"])
        assert core_after["reserved_units"] == 2, (
            f"the area gives back the released unit, got {core_after['reserved_units']}"
        )
        rsa_after = fetch_receiving_site_application(pool["rsa"]["id"])
        assert rsa_after["status"] == "DESIGN_APPROVED", (
            f"the remaining 2 pending units still meet the requirement, got "
            f"{rsa_after['status']}"
        )

        response = api_client.release_redemption(
            pool["redemption_a"]["id"], developer_headers,
            {"reason": "duplicate release attempt"},
        )
        validate_error(response, ApiErrorId.ERR_REDEMPTION_NOT_RELEASABLE.value)

        final = fetch_redemption(pool["redemption_a"]["id"])
        assert final["status"] == "RELEASED", (
            f"the second attempt changes nothing, got {final['status']}"
        )
        assert final["version"] == released["version"], (
            f"the refused release leaves the version at {released['version']}, got "
            f"{final['version']}"
        )
        assert fetch_receiving_area(pool["core_area"]["id"])["reserved_units"] == 2, (
            "the refused release must not give back the unit a second time"
        )
