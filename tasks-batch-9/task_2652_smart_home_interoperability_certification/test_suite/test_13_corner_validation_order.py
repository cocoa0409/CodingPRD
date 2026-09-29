"""The validation ladder walked rung by rung on five write surfaces.

Every request below violates several rules at once, so each test pins the single
error identifier the first violated rung must produce: existence before shape,
shape before enum, enum before the date rules, the date rules before
collection-wide uniqueness, and the compliance rungs of the two-track review in
their own declared order.
"""

from test_helpers import (
    CLOCK_PROGRAMME_START,
    ERR_ACCREDITATION_EXPIRED,
    ERR_CREDIT_AMOUNT_OUT_OF_RANGE,
    ERR_DEVICE_TYPE_NOT_AUTHORIZED,
    ERR_DUPLICATE_NAME,
    ERR_FEATURE_SET_NOT_FOUND,
    ERR_INVALID_DATE_RANGE,
    ERR_INVALID_ENUM_VALUE,
    ERR_INVALID_REQUEST,
    ERR_INVALID_WINDOW_BOUNDS,
    ERR_IP_COMMITMENT_REQUIRED,
    ERR_LISTING_NOT_FOUND,
    ERR_MEMBER_NOT_FOUND,
    ERR_SECURE_BOOT_NOT_VERIFIED,
    ERR_SECURITY_BASELINE_NOT_MET,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_SPECIFICATION_NOT_FOUND,
    LAB_AUTHORIZED,
    LAB_PROVISIONAL,
    MEMBER_REGISTERED,
    PLUGFEST_REGISTRATION_OPEN,
    REVIEW_APPROVED,
    REVIEW_PENDING,
    SESSION_SCHEDULED,
    SPEC_DRAFT,
    SUB_DRAFT,
    SUB_IN_REVIEW,
    UNKNOWN_UUID,
    build_laboratory,
    build_member,
    build_specification,
    feature,
    get_success_data,
    issue_test_plan,
    new_specification,
    new_submission,
    new_test_plan,
    read_laboratory,
    read_ledger,
    read_member,
    read_specification,
    read_submission,
    set_clock,
    start_review,
    submit_submission,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.api_client import api_client
from test_helpers.assertions import assert_cents, assert_states
from test_helpers.factories import (
    accreditation_payload,
    feature_set_payload,
    noncompliance_case_payload,
    plugfest_payload,
    return_for_info_payload,
    security_decision_payload,
    specification_payload,
    test_session_payload,
    tool_access_payload,
)
from test_helpers.fixtures import Ctx
from test_helpers.test_users import (
    ADMIN_HEADERS,
    COMPLIANCE_HEADERS,
    CONFORMANCE_REVIEWER_1,
    CONFORMANCE_REVIEWER_2,
    PUBLIC_HEADERS,
    SECURITY_REVIEWER_1,
    make_conformance_headers,
    make_laboratory_headers,
    make_member_headers,
    make_security_headers,
)

#: A second syntactically valid identifier that never resolves to a stored row.
SECOND_UNKNOWN_UUID = "00000000-0000-4000-8000-000000000001"


def _one_draft_specification():
    """The clock parked at the programme instant and one stored DRAFT version."""
    set_clock(CLOCK_PROGRAMME_START)
    return new_specification(
        version_label="SHIC-1.0",
        security_baseline_level="SB1",
        effective_date="2026-09-01T00:00:00Z",
    )


class TestSpecificationCreateLadder:
    """One create surface violating shape, enum, date and uniqueness rules at once."""

    def test_01_a_missing_field_and_an_out_of_range_number_report_the_shape_failure(self):
        """A create that omits `security_baseline_level` while also inverting its date
        pair reports the shape failure, and so does a `min_plugfest_credits` of 5
        against the declared range of 0 through 4 — never an enum or date error.

        PRD (§2.8): "Every field the endpoint declares as required is present and of
        the declared JSON type, and every numeric field lies inside its declared
        range — otherwise `ERR_INVALID_REQUEST` (400)."

        Design: Corner/validations/specification_shape_enum_date_and_duplicate_rules_fire_in_priority_order
        """
        _one_draft_specification()

        missing_field = specification_payload(
            version_label="SHIC-2.0",
            effective_date="2026-10-01T00:00:00Z",
            sunset_date="2026-09-01T00:00:00Z",
        )
        missing_field.pop("security_baseline_level")
        validate_error(
            api_client.create_specification(missing_field, ADMIN_HEADERS),
            ERR_INVALID_REQUEST,
        )

        out_of_range = specification_payload(
            version_label="SHIC-2.0",
            security_baseline_level="SB2",
            effective_date="2026-10-01T00:00:00Z",
            min_plugfest_credits=5,
        )
        validate_error(
            api_client.create_specification(out_of_range, ADMIN_HEADERS),
            ERR_INVALID_REQUEST,
        )

        _rows, meta = validate_paginated(
            api_client.list_specifications(PUBLIC_HEADERS, limit=10, offset=0)
        )
        assert meta["total_count"] == 1, (
            "neither refused create may store a row, expected total_count 1, "
            "got {}".format(meta["total_count"])
        )

    def test_02_an_unknown_enum_member_outranks_both_the_date_and_duplicate_rules(self):
        """A create that repeats a stored `version_label`, names a baseline level
        outside the declared set and inverts its date pair reports the enum failure,
        because uniqueness is evaluated last of all.

        PRD (§2.8): "Note also where `ERR_DUPLICATE_NAME` sits: dead last,
        deliberately. Every shape, enum, range, state and referential rule is
        evaluated before it, so a request that is simultaneously malformed and a
        duplicate reports the malformation."

        Design: Corner/validations/specification_shape_enum_date_and_duplicate_rules_fire_in_priority_order
        """
        _one_draft_specification()

        response = api_client.create_specification(
            specification_payload(
                version_label="SHIC-1.0",
                security_baseline_level="SB4",
                effective_date="2026-10-01T00:00:00Z",
                sunset_date="2026-09-01T00:00:00Z",
            ),
            ADMIN_HEADERS,
        )

        validate_error(response, ERR_INVALID_ENUM_VALUE)

    def test_03_a_sunset_date_equal_to_the_effective_date_is_not_strictly_after(self):
        """The date rule is strict: a `sunset_date` landing on exactly the
        `effective_date` instant is refused, with nothing else wrong in the request.

        PRD (§3.1): "A `sunset_date` records the instant after which the version is
        scheduled for retirement and defaults to null when unscheduled; when supplied
        it must be strictly after `effective_date`, and otherwise the create is
        rejected with `ERR_INVALID_DATE_RANGE`."

        Design: Corner/validations/specification_shape_enum_date_and_duplicate_rules_fire_in_priority_order
        """
        _one_draft_specification()

        response = api_client.create_specification(
            specification_payload(
                version_label="SHIC-2.0",
                security_baseline_level="SB2",
                effective_date="2026-10-01T00:00:00Z",
                sunset_date="2026-10-01T00:00:00Z",
            ),
            ADMIN_HEADERS,
        )

        validate_error(response, ERR_INVALID_DATE_RANGE)

    def test_04_a_clean_duplicate_reports_uniqueness_and_a_clean_create_is_stored(self):
        """With every earlier rung satisfied the repeated `version_label` finally
        reports uniqueness, and a request that is clean on every rung is stored as
        the second DRAFT version.

        PRD (§3.1): "A `ProgramAdmin` opens one by supplying a `version_label` such
        as `1.0` — between 1 and 32 characters, and unique across every specification
        version ever created, with a repeat rejected as `ERR_DUPLICATE_NAME` —
        together with the `security_baseline_level` the version mandates, one of
        `SB1`, `SB2` or `SB3`, and an `effective_date`, the ISO 8601 UTC instant from
        which the version may be cited by a certification submission."

        Design: Corner/validations/specification_shape_enum_date_and_duplicate_rules_fire_in_priority_order
        """
        first = _one_draft_specification()

        duplicate = api_client.create_specification(
            specification_payload(
                version_label="SHIC-1.0",
                security_baseline_level="SB2",
                effective_date="2026-10-01T00:00:00Z",
            ),
            ADMIN_HEADERS,
        )
        validate_error(duplicate, ERR_DUPLICATE_NAME)

        created = validate_success(
            api_client.create_specification(
                specification_payload(
                    version_label="SHIC-2.0",
                    security_baseline_level="SB2",
                    effective_date="2026-10-01T00:00:00Z",
                    sunset_date="2026-10-02T00:00:00Z",
                    min_plugfest_credits=4,
                ),
                ADMIN_HEADERS,
            ),
            201,
        )

        assert_states(
            created,
            status=SPEC_DRAFT,
            min_plugfest_credits=4,
            feature_set_count=0,
            version=1,
        )
        rows, meta = validate_paginated(
            api_client.list_specifications(PUBLIC_HEADERS, limit=10, offset=0)
        )
        assert meta["total_count"] == 2, (
            "only the two accepted creates are stored, expected total_count 2, "
            "got {}".format(meta["total_count"])
        )
        assert [row["id"] for row in rows] == [first["id"], created["id"]], (
            "the list is ordered by created_at ascending, expected {} then {}, "
            "got {}".format(first["id"], created["id"], [row["id"] for row in rows])
        )


def _plugfest_host():
    """A ratified LIGHTING version and one AUTHORIZED host laboratory."""
    ctx = Ctx()
    set_clock(CLOCK_PROGRAMME_START)
    specification = build_specification(
        features=[feature("CORE_ONOFF", "MANDATORY", 20)],
        version_label="SHIC-1.0",
        security_baseline_level="SB1",
        effective_date="2026-09-01T00:00:00Z",
    )
    laboratory = build_laboratory(
        name="Northbridge Lab",
        bench_capacity=2,
        authorized_device_types=["LIGHTING"],
        accreditation_expires_at="2027-12-31T00:00:00Z",
    )
    ctx.specification_id = specification.specification_id
    ctx.laboratory_id = laboratory.laboratory_id
    return ctx


class TestPlugfestWindowLadder:
    """The window rule and the registration-deadline rule on one create surface."""

    def test_05_window_bounds_are_checked_before_the_registration_deadline(self):
        """A window whose end equals its start is refused on bounds, and so is a
        `window_start` carrying seconds even when the `registration_deadline` also
        sits after it — the deadline rule never gets a say.

        PRD (§2.8): "`window_end` is strictly after `window_start`, and both bounds
        fall exactly on a minute boundary with zero seconds and zero microseconds —
        otherwise `ERR_INVALID_WINDOW_BOUNDS` (422)."

        Design: Corner/validations/plugfest_window_bounds_outrank_the_registration_deadline_rule
        """
        ctx = _plugfest_host()

        empty_window = api_client.create_plugfest(
            plugfest_payload(
                ctx.laboratory_id,
                ctx.specification_id,
                window_start="2026-10-05T09:00:00Z",
                window_end="2026-10-05T09:00:00Z",
                registration_deadline="2026-10-01T00:00:00Z",
            ),
            ADMIN_HEADERS,
        )
        validate_error(empty_window, ERR_INVALID_WINDOW_BOUNDS)

        seconds_and_late_deadline = api_client.create_plugfest(
            plugfest_payload(
                ctx.laboratory_id,
                ctx.specification_id,
                window_start="2026-10-05T09:00:30Z",
                window_end="2026-10-05T17:00:00Z",
                registration_deadline="2026-10-06T00:00:00Z",
            ),
            ADMIN_HEADERS,
        )
        validate_error(seconds_and_late_deadline, ERR_INVALID_WINDOW_BOUNDS)

        _rows, meta = validate_paginated(
            api_client.list_plugfests(PUBLIC_HEADERS, limit=10, offset=0)
        )
        assert meta["total_count"] == 0, (
            "neither refused create may store an event, expected total_count 0, "
            "got {}".format(meta["total_count"])
        )

    def test_06_the_deadline_may_equal_the_window_start_but_not_follow_it(self):
        """With clean bounds a `registration_deadline` one second after
        `window_start` is refused, while a deadline landing on exactly
        `window_start` is accepted and opens registration.

        PRD (§3.7): "The event's `window_start` and `window_end` bound it —
        `window_end` strictly after `window_start`, both on a minute boundary, or
        `ERR_INVALID_WINDOW_BOUNDS` — and a `registration_deadline` fixes the instant
        after which registration is refused, which must be at or before
        `window_start` with equality accepted, or `ERR_INVALID_DATE_RANGE`."

        Design: Corner/validations/plugfest_window_bounds_outrank_the_registration_deadline_rule
        """
        ctx = _plugfest_host()

        one_second_late = api_client.create_plugfest(
            plugfest_payload(
                ctx.laboratory_id,
                ctx.specification_id,
                window_start="2026-10-05T09:00:00Z",
                window_end="2026-10-05T17:00:00Z",
                registration_deadline="2026-10-05T09:00:01Z",
            ),
            ADMIN_HEADERS,
        )
        validate_error(one_second_late, ERR_INVALID_DATE_RANGE)

        created = validate_success(
            api_client.create_plugfest(
                plugfest_payload(
                    ctx.laboratory_id,
                    ctx.specification_id,
                    window_start="2026-10-05T09:00:00Z",
                    window_end="2026-10-05T17:00:00Z",
                    registration_deadline="2026-10-05T09:00:00Z",
                ),
                ADMIN_HEADERS,
            ),
            201,
        )

        assert_states(
            created,
            state=PLUGFEST_REGISTRATION_OPEN,
            distinct_vendor_count=0,
            locked_at=None,
        )
        rows, meta = validate_paginated(
            api_client.list_plugfests(
                PUBLIC_HEADERS, host_laboratory_id=ctx.laboratory_id, limit=10, offset=0
            )
        )
        assert meta["total_count"] == 1, (
            "only the accepted event is stored under this host, expected "
            "total_count 1, got {}".format(meta["total_count"])
        )
        assert rows[0]["id"] == created["id"], (
            "the host filter must return the accepted event, expected {}, got "
            "{}".format(created["id"], rows[0]["id"])
        )

    def test_07_a_vendor_quorum_outside_its_declared_range_is_a_shape_failure(self):
        """A `min_distinct_vendors` of 9 sits outside the declared 2 through 8 range,
        so the create is refused on shape rather than on any window or date rule.

        PRD (§2.8): "Every field the endpoint declares as required is present and of
        the declared JSON type, and every numeric field lies inside its declared
        range — otherwise `ERR_INVALID_REQUEST` (400)."

        Design: Corner/validations/plugfest_window_bounds_outrank_the_registration_deadline_rule
        """
        ctx = _plugfest_host()

        response = api_client.create_plugfest(
            plugfest_payload(
                ctx.laboratory_id,
                ctx.specification_id,
                window_start="2026-10-05T09:00:00Z",
                window_end="2026-10-05T17:00:00Z",
                registration_deadline="2026-10-01T00:00:00Z",
                min_distinct_vendors=9,
            ),
            ADMIN_HEADERS,
        )

        validate_error(response, ERR_INVALID_REQUEST)


class TestUnknownIdentifiersOutrankShapeAndEnum:
    """Existence resolution running ahead of every shape and enum check."""

    def test_08_an_unresolvable_path_identifier_is_reported_before_a_bad_enum(self):
        """A tool-access decision aimed at a member id that resolves to nothing
        reports the member as missing even though its `decision` is not a declared
        enum member, and a read of an unknown version reports the same way.

        PRD (§2.6): "Templated segments are resolved strictly left to right, and the
        first segment that fails to resolve decides the response: HTTP 404 carrying
        the error identifier for that resource family."

        Design: Corner/validations/unknown_ids_are_reported_not_found_before_any_shape_or_enum_check
        """
        _one_draft_specification()

        unknown_member = api_client.set_tool_access(
            UNKNOWN_UUID, tool_access_payload("NOT_A_DECISION"), ADMIN_HEADERS
        )
        validate_error(unknown_member, ERR_MEMBER_NOT_FOUND)

        unknown_specification = api_client.get_specification(UNKNOWN_UUID, PUBLIC_HEADERS)
        validate_error(unknown_specification, ERR_SPECIFICATION_NOT_FOUND)

    def test_09_dangling_body_references_are_reported_before_shape_and_enum_checks(self):
        """A feature-set create naming an unknown specification reports the missing
        version even with a required field omitted; an unknown dependency reports the
        missing feature set; and a case create naming an unknown listing reports the
        missing listing rather than its undeclared category.

        PRD (§2.6): "Foreign keys supplied inside a request body are resolved with the
        same discipline, and the same HTTP 404 error identifiers, immediately after
        path resolution succeeds."

        Design: Corner/validations/unknown_ids_are_reported_not_found_before_any_shape_or_enum_check
        """
        specification = _one_draft_specification()

        missing_specification = feature_set_payload(
            UNKNOWN_UUID,
            device_type="LIGHTING",
            feature_code="CORE_ONOFF",
            obligation="MANDATORY",
        )
        missing_specification.pop("test_case_count")
        validate_error(
            api_client.create_feature_set(missing_specification, ADMIN_HEADERS),
            ERR_SPECIFICATION_NOT_FOUND,
        )

        missing_dependency = feature_set_payload(
            specification["id"],
            device_type="LIGHTING",
            feature_code="CORE_DIM",
            obligation="CONDITIONAL",
            test_case_count=10,
            depends_on_feature_set_id=SECOND_UNKNOWN_UUID,
        )
        validate_error(
            api_client.create_feature_set(missing_dependency, ADMIN_HEADERS),
            ERR_FEATURE_SET_NOT_FOUND,
        )

        missing_listing = noncompliance_case_payload(
            UNKNOWN_UUID,
            category="NOT_A_CATEGORY",
            evidence_summary="Reported interoperability defect awaiting triage.",
            claimed_impact_units=10,
        )
        validate_error(
            api_client.create_noncompliance_case(missing_listing, COMPLIANCE_HEADERS),
            ERR_LISTING_NOT_FOUND,
        )

        _rows, meta = validate_paginated(
            api_client.list_feature_sets(
                PUBLIC_HEADERS,
                specification_id=specification["id"],
                limit=10,
                offset=0,
            )
        )
        assert meta["total_count"] == 0, (
            "no refused create may store a feature set, expected total_count 0, "
            "got {}".format(meta["total_count"])
        )
        stored = read_specification(specification["id"])
        assert stored["feature_set_count"] == 0, (
            "the version's feature_set_count must stay 0, got {}".format(
                stored["feature_set_count"]
            )
        )


def _registered_member():
    """One REGISTERED member with an untouched, empty credit account."""
    set_clock(CLOCK_PROGRAMME_START)
    return build_member(
        credit_cents=0,
        legal_name="Acme Devices",
        contact_email="ops@acme.test",
        tier="ADOPTER",
    )


class TestCreditPurchaseRange:
    """The purchase band, and the type check that sits above it on the ladder."""

    def test_10_amounts_below_and_above_the_declared_band_are_refused(self):
        """A purchase of 999 cents and a purchase of 100000001 cents both fall
        outside the declared band and are refused, leaving the account at zero.

        PRD (§3.2): "Credit is purchased either by the `ProgramAdmin` or by the member
        itself, by supplying `amount_cents`; a purchase must be at least 1000 cents
        and at most 100000000 cents, and anything outside that band is rejected with
        `ERR_CREDIT_AMOUNT_OUT_OF_RANGE`."

        Design: Corner/validations/credit_purchase_amount_outside_its_declared_range_is_rejected
        """
        ctx = _registered_member()

        too_small = api_client.purchase_credits(
            ctx.member_id, {"amount_cents": 999}, ADMIN_HEADERS
        )
        validate_error(too_small, ERR_CREDIT_AMOUNT_OUT_OF_RANGE)
        assert_cents(
            read_member(ctx.member_id)["credit_balance_cents"],
            0,
            "credit_balance_cents after the refused 999-cent purchase",
        )

        too_large = api_client.purchase_credits(
            ctx.member_id, {"amount_cents": 100000001}, ADMIN_HEADERS
        )
        validate_error(too_large, ERR_CREDIT_AMOUNT_OUT_OF_RANGE)

        member = read_member(ctx.member_id)
        assert_cents(
            member["credits_purchased_cents"],
            0,
            "credits_purchased_cents after two refused purchases",
        )
        assert_cents(
            member["credit_balance_cents"],
            0,
            "credit_balance_cents after two refused purchases",
        )

    def test_11_a_string_amount_is_a_shape_failure_not_a_range_failure(self):
        """An `amount_cents` sent as a JSON string is refused on the request-shape
        rung, which sits far above the purchase-range rung, so the range error id
        cannot appear even though the string spells a legal amount.

        PRD (§2.8): "Requests are therefore validated in one fixed, strictly ordered
        ladder, and the **first** rung whose condition is violated decides the
        response: no later rung is evaluated, and no later rung's error identifier can
        appear in its place."

        Design: Corner/validations/credit_purchase_amount_outside_its_declared_range_is_rejected
        """
        ctx = _registered_member()

        response = api_client.purchase_credits(
            ctx.member_id, {"amount_cents": "1000"}, ADMIN_HEADERS
        )

        validate_error(response, ERR_INVALID_REQUEST)
        assert_cents(
            read_member(ctx.member_id)["credit_balance_cents"],
            0,
            "credit_balance_cents after the refused string amount",
        )

    def test_12_both_inclusive_band_ends_are_accepted_and_accumulate(self):
        """Purchases of exactly 1000 and exactly 100000000 cents are both accepted and
        accumulate to 100001000 cents of spendable balance, with nothing consumed and
        nothing escrowed; buying credit does not advance onboarding.

        PRD (§3.2): "Between those two sits escrow: `escrowed_credit_cents` is the
        total of `fee_escrowed_cents` across every submission belonging to the member,
        and `credit_balance_cents` — the spendable, unescrowed figure — is
        `credits_purchased_cents` reduced by `credits_consumed_cents` and reduced
        again by `escrowed_credit_cents`."

        Design: Corner/validations/credit_purchase_amount_outside_its_declared_range_is_rejected
        """
        ctx = _registered_member()

        lower_end = validate_success(
            api_client.purchase_credits(
                ctx.member_id, {"amount_cents": 1000}, ADMIN_HEADERS
            )
        )
        assert_cents(
            lower_end["credits_purchased_cents"],
            1000,
            "credits_purchased_cents after the minimum purchase",
        )

        upper_end = validate_success(
            api_client.purchase_credits(
                ctx.member_id, {"amount_cents": 100000000}, ADMIN_HEADERS
            )
        )
        assert_cents(
            upper_end["credits_purchased_cents"],
            100001000,
            "credits_purchased_cents after both purchases",
        )
        assert_cents(
            upper_end["credit_balance_cents"],
            100001000,
            "credit_balance_cents after both purchases",
        )

        ledger = read_ledger(ctx.member_id)
        assert_cents(
            ledger["credits_purchased_cents"], 100001000, "ledger credits_purchased_cents"
        )
        assert_cents(ledger["credits_consumed_cents"], 0, "ledger credits_consumed_cents")
        assert_cents(ledger["escrowed_credit_cents"], 0, "ledger escrowed_credit_cents")
        assert_cents(ledger["balance_cents"], 100001000, "ledger balance_cents")

        member = read_member(ctx.member_id)
        assert member["onboarding_state"] == MEMBER_REGISTERED, (
            "paying for credit does not move onboarding, expected REGISTERED, got "
            "{}".format(member["onboarding_state"])
        )
        assert member["good_standing"] is False, (
            "a member with no commitment and no tooling is not in good standing, "
            "got {!r}".format(member["good_standing"])
        )


def _two_baseline_programme():
    """Two ratified versions, one SB1 and one SB2, and two funded members whose IP
    commitments are scoped to different versions, each with drafts pinned to SB2."""
    ctx = Ctx()
    set_clock(CLOCK_PROGRAMME_START)
    sb1 = build_specification(
        features=[feature("CORE_ONOFF", "MANDATORY", 20)],
        version_label="SHIC-1.0",
        security_baseline_level="SB1",
        effective_date="2026-09-01T00:00:00Z",
    )
    sb2 = build_specification(
        features=[feature("CORE_ONOFF", "MANDATORY", 20, security_relevant=True)],
        version_label="SHIC-2.0",
        security_baseline_level="SB2",
        effective_date="2026-09-01T00:00:00Z",
    )
    misscoped = build_member(
        scope_specification_id=sb1.specification_id,
        credit_cents=1000000,
        legal_name="Acme Devices",
    )
    scoped = build_member(
        scope_specification_id=sb2.specification_id,
        credit_cents=1000000,
        legal_name="Borea Labs",
    )
    ctx.sb1_id = sb1.specification_id
    ctx.sb2_id = sb2.specification_id
    ctx.misscoped_id = misscoped.member_id
    ctx.scoped_id = scoped.member_id
    ctx.misscoped_draft = new_submission(
        ctx.misscoped_id, ctx.sb2_id, ["CORE_ONOFF"], device_model="AL-100"
    )
    ctx.no_secure_boot = new_submission(
        ctx.scoped_id,
        ctx.sb2_id,
        ["CORE_ONOFF"],
        device_model="BL-100",
        declared_secure_boot=False,
    )
    ctx.unsigned_updates = new_submission(
        ctx.scoped_id,
        ctx.sb2_id,
        ["CORE_ONOFF"],
        device_model="BL-200",
        declared_firmware_update_capability="OTA_UNSIGNED",
    )
    ctx.clean_draft = new_submission(
        ctx.scoped_id, ctx.sb2_id, ["CORE_ONOFF"], device_model="BL-300"
    )
    return ctx


def _walk_clean_draft_to_a_second_review(ctx):
    """Submit, return for information with CONF1, resubmit, then let CONF2 pick it up."""
    submit_submission(ctx.clean_draft["id"], ctx.scoped_id)
    start_review(ctx.clean_draft["id"], CONFORMANCE_REVIEWER_1)
    get_success_data(
        api_client.return_for_info(
            ctx.clean_draft["id"],
            return_for_info_payload("Attestation key provenance evidence missing"),
            make_conformance_headers(CONFORMANCE_REVIEWER_1),
        )
    )
    submit_submission(ctx.clean_draft["id"], ctx.scoped_id)
    start_review(ctx.clean_draft["id"], CONFORMANCE_REVIEWER_2)


class TestSubmitAndSecurityDecisionLadder:
    """The IP, baseline, attestation and segregation rungs in their declared order."""

    def test_13_an_ip_commitment_scoped_to_another_version_blocks_the_submit(self):
        """A member whose commitment names the SB1 version cannot submit a draft
        pinned to the SB2 version, however impeccable its security declarations are.

        PRD (§2.8): "**IP scope.** `ERR_IP_COMMITMENT_REQUIRED` (409) when the
        member's `ip_scope_specification_id` does not equal the submission's pinned
        `specification_id`."

        Design: Corner/validations/ip_scope_baseline_attestation_and_segregation_gates_fire_in_priority_order
        """
        ctx = _two_baseline_programme()

        response = api_client.submit_submission(
            ctx.misscoped_draft["id"], headers=make_member_headers(ctx.misscoped_id)
        )

        validate_error(response, ERR_IP_COMMITMENT_REQUIRED)
        stored = read_submission(ctx.misscoped_draft["id"])
        assert stored["state"] == SUB_DRAFT, (
            "the refused submit leaves the draft alone, expected DRAFT, got "
            "{}".format(stored["state"])
        )
        assert_cents(stored["fee_escrowed_cents"], 0, "fee_escrowed_cents after refusal")

    def test_14_a_hardened_baseline_refuses_both_weak_self_declarations(self):
        """Against the SB2 version a `declared_secure_boot` of false and a
        `declared_firmware_update_capability` of OTA_UNSIGNED are each refused at
        submit, and neither draft escrows a cent.

        PRD (§3.8): "From `DRAFT` the submission requires a pinned specification whose
        `status` is `RATIFIED`, a member in good standing, and — where that
        specification's `security_baseline_level` is `SB2` or `SB3` — a
        `declared_secure_boot` of true together with a
        `declared_firmware_update_capability` of exactly `OTA_SIGNED`; a
        self-declaration of `OTA_UNSIGNED` or `NONE` against a hardened baseline is
        refused with `ERR_SECURITY_BASELINE_NOT_MET`."

        Design: Corner/validations/ip_scope_baseline_attestation_and_segregation_gates_fire_in_priority_order
        """
        ctx = _two_baseline_programme()

        for label, draft in (
            ("declared_secure_boot false", ctx.no_secure_boot),
            ("OTA_UNSIGNED updates", ctx.unsigned_updates),
        ):
            response = api_client.submit_submission(
                draft["id"], headers=make_member_headers(ctx.scoped_id)
            )
            validate_error(response, ERR_SECURITY_BASELINE_NOT_MET)
            stored = read_submission(draft["id"])
            assert stored["state"] == SUB_DRAFT, (
                "the {} draft stays DRAFT after refusal, got {}".format(
                    label, stored["state"]
                )
            )
            assert_cents(
                stored["fee_escrowed_cents"],
                0,
                "fee_escrowed_cents on the {} draft".format(label),
            )

    def test_15_the_disqualified_reviewer_is_turned_away_before_their_findings_are_read(self):
        """One security-decision body that is wrong on identity, on baseline and on
        attestation reports the segregation failure first; with a clean reviewer it
        reports the baseline failure; with a signed capability it finally reports the
        attestation failure; and only the fourth attempt is recorded.

        PRD (§2.10): "Either violation is rejected with `ERR_SEGREGATION_OF_DUTIES`
        and HTTP 409, and because that check sits at rung 24 of §2.8's ladder it is
        evaluated *before* the security-baseline and device-attestation checks that
        follow it — a disqualified reviewer is turned away on identity grounds even
        when their findings would also have failed on substance."

        Design: Corner/validations/ip_scope_baseline_attestation_and_segregation_gates_fire_in_priority_order
        """
        ctx = _two_baseline_programme()
        _walk_clean_draft_to_a_second_review(ctx)
        submission_id = ctx.clean_draft["id"]
        unverified_and_unsigned = security_decision_payload(
            "APPROVE",
            secure_boot_verified=False,
            verified_firmware_update_capability="OTA_UNSIGNED",
        )

        disqualified = api_client.security_decision(
            submission_id,
            unverified_and_unsigned,
            make_security_headers(CONFORMANCE_REVIEWER_1),
        )
        validate_error(disqualified, ERR_SEGREGATION_OF_DUTIES)

        weak_capability = api_client.security_decision(
            submission_id,
            unverified_and_unsigned,
            make_security_headers(SECURITY_REVIEWER_1),
        )
        validate_error(weak_capability, ERR_SECURITY_BASELINE_NOT_MET)

        unverified_boot = api_client.security_decision(
            submission_id,
            security_decision_payload(
                "APPROVE",
                secure_boot_verified=False,
                verified_firmware_update_capability="OTA_SIGNED",
            ),
            make_security_headers(SECURITY_REVIEWER_1),
        )
        validate_error(unverified_boot, ERR_SECURE_BOOT_NOT_VERIFIED)

        before = read_submission(submission_id)
        assert_states(
            before,
            security_review_state=REVIEW_PENDING,
            secure_boot_verified=None,
            security_reviewer_user_id=None,
        )

        accepted = validate_success(
            api_client.security_decision(
                submission_id,
                security_decision_payload(
                    "APPROVE",
                    secure_boot_verified=True,
                    verified_firmware_update_capability="OTA_SIGNED",
                ),
                make_security_headers(SECURITY_REVIEWER_1),
            )
        )

        assert_states(
            accepted,
            security_review_state=REVIEW_APPROVED,
            secure_boot_verified=True,
            verified_firmware_update_capability="OTA_SIGNED",
            security_reviewer_user_id=SECURITY_REVIEWER_1,
            state=SUB_IN_REVIEW,
        )

    def test_16_the_resubmission_neither_escrows_again_nor_forgets_the_first_reviewer(self):
        """After return-for-information and resubmission the fee is still escrowed
        exactly once, `revision_round` is 1, and the reviewer recorded by the
        return-for-information is the one the segregation gate reads.

        PRD (§3.8): "The same call also serves the resubmission path
        `RETURNED_FOR_INFO → SUBMITTED`, which repeats the ratification, good-standing
        and security-baseline checks but *not* the balance check, and which escrows
        nothing a second time — `fee_escrowed_cents` already equals
        `certification_fee_cents`, so the member's ledger is untouched — while
        resetting `conformance_review_state` from `RETURNED` back to `PENDING`."

        Design: Corner/validations/ip_scope_baseline_attestation_and_segregation_gates_fire_in_priority_order
        """
        ctx = _two_baseline_programme()
        _walk_clean_draft_to_a_second_review(ctx)

        stored = read_submission(ctx.clean_draft["id"])

        # LIGHTING at 120000, one declared code at 15000, SB2 surcharge at 50000.
        assert_cents(stored["certification_fee_cents"], 185000, "certification_fee_cents")
        assert_cents(stored["fee_escrowed_cents"], 185000, "fee_escrowed_cents")
        assert stored["revision_round"] == 1, (
            "one return-for-information advances revision_round to 1, got {}".format(
                stored["revision_round"]
            )
        )
        assert stored["conformance_reviewer_user_id"] == CONFORMANCE_REVIEWER_1, (
            "the return-for-information recorded CONF1 and the second pick-up does "
            "not overwrite it, got {!r}".format(stored["conformance_reviewer_user_id"])
        )
        ledger = read_ledger(ctx.scoped_id)
        assert_cents(ledger["escrowed_credit_cents"], 185000, "ledger escrowed_credit_cents")
        assert_cents(ledger["balance_cents"], 815000, "ledger balance_cents")


def _thermostat_plan_and_three_laboratories():
    """An issued THERMOSTAT plan, a LIGHTING-only laboratory whose accreditation lapses
    on 2026-09-10, a THERMOSTAT laboratory good until 2027, and a PROVISIONAL
    THERMOSTAT laboratory whose accreditation lapses on 2026-09-05."""
    ctx = Ctx()
    set_clock(CLOCK_PROGRAMME_START)
    specification = build_specification(
        features=[
            feature("CORE_ONOFF", "MANDATORY", 20),
            feature("T_CORE", "MANDATORY", 10, device_type="THERMOSTAT"),
        ],
        version_label="SHIC-1.0",
        security_baseline_level="SB1",
        effective_date="2026-09-01T00:00:00Z",
    )
    lighting_only = build_laboratory(
        name="Northbridge Lab",
        bench_capacity=2,
        authorized_device_types=["LIGHTING"],
        accreditation_expires_at="2026-09-10T00:00:00Z",
    )
    thermostat_lab = build_laboratory(
        name="Southgate Lab",
        bench_capacity=2,
        authorized_device_types=["THERMOSTAT"],
        accreditation_expires_at="2027-12-31T00:00:00Z",
    )
    lapsed_provisional = build_laboratory(
        authorize=False,
        name="Eastvale Lab",
        bench_capacity=1,
        authorized_device_types=["THERMOSTAT"],
        accreditation_expires_at="2026-09-05T00:00:00Z",
    )
    member = build_member(
        scope_specification_id=specification.specification_id,
        credit_cents=1000000,
        legal_name="Acme Devices",
    )
    submission = new_submission(
        member.member_id,
        specification.specification_id,
        ["T_CORE"],
        device_type="THERMOSTAT",
        device_model="TH-100",
    )
    submit_submission(submission["id"], member.member_id)
    in_review = start_review(submission["id"], CONFORMANCE_REVIEWER_1)
    plan = new_test_plan(submission["id"], in_review["version"])
    issue_test_plan(plan["id"])
    ctx.lighting_only_id = lighting_only.laboratory_id
    ctx.thermostat_lab_id = thermostat_lab.laboratory_id
    ctx.lapsed_provisional_id = lapsed_provisional.laboratory_id
    ctx.plan_id = plan["id"]
    return ctx


class TestAccreditationCurrencyOutranksDeviceClass:
    """The same booking refused on two different rungs as the clock moves."""

    def test_17_a_lapsed_accreditation_masks_the_device_class_refusal(self):
        """While its accreditation is current the LIGHTING-only laboratory is refused
        the THERMOSTAT booking on device class; once the clock passes its expiry the
        very same booking is refused on accreditation currency instead.

        PRD (§3.6): "The laboratory's `accreditation_expires_at` must be strictly after
        the logical clock's current instant, or the booking is refused with
        `ERR_ACCREDITATION_EXPIRED`."

        Design: Corner/validations/expired_accreditation_outranks_the_device_type_authorization_check
        """
        ctx = _thermostat_plan_and_three_laboratories()

        while_current = api_client.create_test_session(
            test_session_payload(
                ctx.plan_id,
                ctx.lighting_only_id,
                bench_index=1,
                window_start="2026-09-02T09:00:00Z",
                window_end="2026-09-02T13:00:00Z",
                session_type="INTEROP",
            ),
            ADMIN_HEADERS,
        )
        validate_error(while_current, ERR_DEVICE_TYPE_NOT_AUTHORIZED)

        set_clock("2026-09-11T00:00:00Z")
        once_lapsed = api_client.create_test_session(
            test_session_payload(
                ctx.plan_id,
                ctx.lighting_only_id,
                bench_index=1,
                window_start="2026-09-12T09:00:00Z",
                window_end="2026-09-12T13:00:00Z",
                session_type="INTEROP",
            ),
            ADMIN_HEADERS,
        )
        validate_error(once_lapsed, ERR_ACCREDITATION_EXPIRED)

        laboratory = read_laboratory(ctx.lighting_only_id)
        assert laboratory["accreditation_status"] == LAB_AUTHORIZED, (
            "a lapsed expiry does not itself move the status, expected AUTHORIZED, "
            "got {}".format(laboratory["accreditation_status"])
        )
        assert laboratory["reserved_bench_minutes"] == 0, (
            "neither refused booking may reserve bench time, expected 0, got "
            "{}".format(laboratory["reserved_bench_minutes"])
        )

    def test_18_a_lapsed_expiry_also_blocks_authorization_while_a_current_lab_books(self):
        """The PROVISIONAL laboratory whose expiry has already passed cannot be
        authorized and stays PROVISIONAL, while the THERMOSTAT laboratory whose
        accreditation is still current takes the same window cleanly.

        PRD (§3.3): "Both `AUTHORIZE` and `REINSTATE` additionally require that
        `accreditation_expires_at` is strictly after the logical clock's current
        instant, and a lapsed accreditation blocks either with
        `ERR_ACCREDITATION_EXPIRED`; a decision attempted from a status the transition
        table does not permit is instead rejected with `ERR_INVALID_LABORATORY_STATE`."

        Design: Corner/validations/expired_accreditation_outranks_the_device_type_authorization_check
        """
        ctx = _thermostat_plan_and_three_laboratories()
        set_clock("2026-09-11T00:00:00Z")

        refused = api_client.accreditation_decision(
            ctx.lapsed_provisional_id, accreditation_payload("AUTHORIZE"), ADMIN_HEADERS
        )
        validate_error(refused, ERR_ACCREDITATION_EXPIRED)
        assert read_laboratory(ctx.lapsed_provisional_id)["accreditation_status"] == (
            LAB_PROVISIONAL
        ), "the refused authorization leaves the laboratory PROVISIONAL, got {}".format(
            read_laboratory(ctx.lapsed_provisional_id)["accreditation_status"]
        )

        session = validate_success(
            api_client.create_test_session(
                test_session_payload(
                    ctx.plan_id,
                    ctx.thermostat_lab_id,
                    bench_index=1,
                    window_start="2026-09-12T09:00:00Z",
                    window_end="2026-09-12T13:00:00Z",
                    session_type="INTEROP",
                ),
                make_laboratory_headers(ctx.thermostat_lab_id),
            ),
            201,
        )

        assert_states(session, state=SESSION_SCHEDULED, reserved_minutes=240)
        assert read_laboratory(ctx.thermostat_lab_id)["reserved_bench_minutes"] == 240, (
            "the four-hour window reserves 240 minutes, got {}".format(
                read_laboratory(ctx.thermostat_lab_id)["reserved_bench_minutes"]
            )
        )
        rows, meta = validate_paginated(
            api_client.list_test_sessions(
                ADMIN_HEADERS, test_plan_id=ctx.plan_id, limit=10, offset=0
            )
        )
        assert meta["total_count"] == 1, (
            "only the accepted booking is stored against the plan, expected "
            "total_count 1, got {}".format(meta["total_count"])
        )
        assert rows[0]["id"] == session["id"], (
            "the plan filter must return the accepted session, expected {}, got "
            "{}".format(session["id"], rows[0]["id"])
        )
