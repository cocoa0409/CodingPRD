"""Authority and optimistic concurrency in the TDR program.

Three families of rule live here, and they are deliberately kept apart because
the program refuses a request for three quite different reasons.

The first is *authority by role*: each exclusive step of the severance chain
belongs to exactly one role, and the endpoint refuses every other role before it
so much as looks at the record's state.  Two rules go beyond an allow-list —
segregation of duties, which compares the acting operator identity against the
identity already recorded on the audit trail, and channel-role agreement, which
pairs a market channel with the party entitled to open it.

The second is *authority by ownership*: `Landowner` and `Developer` are peers on
the split endpoint, so role membership admits them both while the ownership
comparison against `holder_party_id` admits only the holder.

The third is *optimistic concurrency*: three write endpoints make the client
declare the parent version it last observed, precisely because repeating the
write is legitimate and nothing else would catch a submission that reasons about
a figure the registry has already moved.  Each refusal is checked to be
completely inert, and each retry with a freshly read version is checked to
succeed — including the denormalized holdings counters that must reconcile after
an issuance, a split, a sale and a retirement, all readable the instant the
response returns.
"""
import pytest

from test_helpers import (
    ADMIN_USER_ID,
    CANONICAL_BASELINE_UNITS,
    CANONICAL_PARCEL,
    DEFAULT_CLOCK,
    MONITOR_USER_ID,
    MONITOR_USER_ID_ALT,
    NON_EXISTENT_UUID,
    REVIEWER_USER_ID,
    TEST_USERS,
    account_action_payload,
    allocate_redemption_payload,
    api_client,
    ApiErrorId,
    approve_application,
    assert_certificate,
    assert_certificate_redemption,
    assert_certificate_transfer,
    assert_conservation_easement,
    assert_market_transaction,
    assert_monitoring_inspection,
    assert_party,
    assert_receiving_site_application,
    assert_same_date,
    assert_same_instant,
    assert_sending_area,
    assert_sending_parcel,
    assert_severance_application,
    create_active_receiving_area,
    create_active_sending_area,
    create_market_transaction_payload,
    create_sending_area_payload,
    credit_party,
    design_decision,
    enroll_parcel,
    fetch_application,
    fetch_certificate,
    fetch_easement,
    fetch_inspection,
    fetch_parcel,
    fetch_party,
    fetch_receiving_area,
    fetch_receiving_site_application,
    fetch_sending_area,
    file_receiving_site_application,
    file_severance,
    make_admin_headers,
    make_developer_headers,
    make_landowner_headers,
    make_monitor_headers,
    make_reviewer_headers,
    program_cash_total_now,
    publish_appraisal_schedule,
    register_bank,
    register_developer,
    register_landowner,
    retire_certificate_payload,
    set_clock,
    setup_certified_severance,
    setup_developer_holding_certificate,
    setup_frozen_certificate,
    split_certificate_payload,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
CLOCK = DEFAULT_CLOCK

# The canonical sending-area geometry used throughout: V1_NET_ACRE at 0.25 units
# per acre over the 100.00 / 22.00 / PRIME / 2-dwelling parcel, which fixes a
# 22-unit baseline allocation.
AREA_KWARGS = {
    "neighborhood_code": "NB-EAST",
    "allocation_formula_version": "V1_NET_ACRE",
    "base_rate_units_per_acre": 0.25,
    "gross_discount_factor": 0.80,
    "equity_tier": "UNDERSERVED",
    "sending_cap_units": 200,
}

# NB-EAST appraisal calendar: 1_234_567 cents per unit corrected by +250 bps, so
# the equity-adjusted per-unit value rounds half up to 1_265_431 cents.
SCHEDULE_PER_UNIT_CENTS = 1_234_567
SCHEDULE_EQUITY_BPS = 250
ADJUSTED_PER_UNIT_CENTS = 1_265_431


def _filed_severance() -> dict:
    """Clock, a landowner, a developer, an ACTIVE sending area, the canonical
    parcel and a freshly filed SUBMITTED severance application."""
    set_clock(CLOCK)
    landowner = register_landowner(neighborhood_code="NB-EAST")
    developer = register_developer(neighborhood_code="NB-CORE")
    area = create_active_sending_area(**AREA_KWARGS)
    parcel = enroll_parcel(landowner["id"], area["id"], **CANONICAL_PARCEL)
    application = file_severance(parcel["id"], landowner["id"], CANONICAL_BASELINE_UNITS)
    return {
        "landowner": landowner,
        "developer": developer,
        "area": area,
        "parcel": parcel,
        "application": application,
    }


class TestSeveranceChainRoleExclusivity:
    """Each exclusive step of the severance chain admits exactly one role."""

    def test_only_the_severance_reviewer_may_screen_a_filed_application(self):
        """Five of the six roles are refused the screening step; the reviewer is not.

        PRD §2.1: "If the headers are well formed but the named role is not authorized for the endpoint being called, the request is rejected with `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."
        PRD §2.1: "A `SeveranceReviewer` is a planning-department reviewer who screens severance applications and records the approve, revise, or deny decision — and who may never certify, which is precisely what gives the segregation-of-duties rule its force."
        PRD §3.4: "A `SeveranceReviewer` takes a filed application into review, moving it `SUBMITTED → UNDER_REVIEW`, optionally recording a `screening_note`, writing the acting `X-User-ID` into `screened_by_user_id`, and incrementing the application's `version`."
        PRD §3.4: "`applied_formula_version`, `screened_by_user_id`, `decided_by_user_id`, `certified_by_user_id`, `decision_note`, and `denial_reason` all begin unset."

        Design: Corner/rbac/each_exclusive_step_of_the_severance_chain_refuses_every_other_role
        """
        scenario = _filed_severance()
        filed = scenario["application"]
        app_id = filed["id"]
        assert filed["status"] == "SUBMITTED", f"a fresh filing opens SUBMITTED, got {filed['status']}"
        assert filed["version"] == 1, f"a fresh filing opens at version 1, got {filed['version']}"
        assert filed.get("screened_by_user_id") is None, "screened_by_user_id begins unset"

        refused = [
            ("Landowner", make_landowner_headers(scenario["landowner"]["id"])),
            ("Developer", make_developer_headers(scenario["developer"]["id"])),
            ("ProgramAdministrator", ADMIN),
            ("DesignReviewBoard", TEST_USERS["design_board_headers"]),
            ("EasementMonitor", make_monitor_headers(MONITOR_USER_ID)),
        ]
        for role, headers in refused:
            resp = api_client.screen_severance_application(app_id, headers, {})
            validate_error(resp, ApiErrorId.ERR_ROLE_NOT_PERMITTED.value)

        untouched = fetch_application(app_id)
        for field in ("status", "version", "revision_round", "requested_units",
                      "allocated_units", "residual_units_retained", "updated_at"):
            assert untouched[field] == filed[field], (
                f"a refused screening must leave {field} untouched: "
                f"{untouched[field]!r} != {filed[field]!r}"
            )
        assert untouched.get("screened_by_user_id") is None, (
            "a refused screening must not record an auditor identity"
        )

        screened = validate_success(
            api_client.screen_severance_application(
                app_id, make_reviewer_headers(REVIEWER_USER_ID),
                {"screening_note": "intake review opened"},
            )
        )
        assert_severance_application(screened)
        assert screened["id"] == app_id, "screening returns the same application"
        assert screened["status"] == "UNDER_REVIEW", (
            f"the reviewer moves the application to UNDER_REVIEW, got {screened['status']}"
        )
        assert screened["version"] == 2, (
            f"screening increments the application version to 2, got {screened['version']}"
        )
        assert screened["screened_by_user_id"] == REVIEWER_USER_ID, (
            "the acting reviewer identity is recorded in screened_by_user_id"
        )

    def test_certification_and_the_review_decision_refuse_the_wrong_role_first(self):
        """Authorization is decided before the record's own state is consulted.

        PRD §2.10: "The checks below form one global ladder, evaluated strictly from the top; the first check that fails decides the response, and no later check is consulted."
        PRD §2.10: "**Authorization** — the acting role appears in the endpoint's authorized list; otherwise `ERR_ROLE_NOT_PERMITTED` (403). Applies to every endpoint."
        PRD §2.10: "14. The severance application is `APPROVED` before certification; otherwise `ERR_APPLICATION_NOT_APPROVED` (409)."
        PRD §3.5: "Only a `ProgramAdministrator` may certify, they may attach an optional `recording_note`, and the response is the newly issued certificate rather than the application."
        PRD §3.4: "All three branches require the application to be `UNDER_REVIEW`, otherwise `ERR_APPLICATION_NOT_IN_REVIEW`, and all three write the acting `X-User-ID` into `decided_by_user_id` and increment the application's `version`."

        Design: Corner/rbac/each_exclusive_step_of_the_severance_chain_refuses_every_other_role
        """
        scenario = _filed_severance()
        app_id = scenario["application"]["id"]
        screened = validate_success(
            api_client.screen_severance_application(
                app_id, make_reviewer_headers(REVIEWER_USER_ID), {}
            )
        )
        assert screened["status"] == "UNDER_REVIEW", "precondition: the application is in review"

        # The reviewer who may screen and decide may never certify.  The application
        # is UNDER_REVIEW rather than APPROVED, so a state-first implementation would
        # answer ERR_APPLICATION_NOT_APPROVED; authorization sits above that rung.
        validate_error(
            api_client.certify_severance_application(
                app_id, make_reviewer_headers(REVIEWER_USER_ID), {}
            ),
            ApiErrorId.ERR_ROLE_NOT_PERMITTED.value,
        )
        for headers in (
            make_landowner_headers(scenario["landowner"]["id"]),
            make_developer_headers(scenario["developer"]["id"]),
            TEST_USERS["design_board_headers"],
            make_monitor_headers(MONITOR_USER_ID),
        ):
            validate_error(
                api_client.certify_severance_application(app_id, headers, {}),
                ApiErrorId.ERR_ROLE_NOT_PERMITTED.value,
            )

        # The decision endpoint belongs to the reviewer alone.
        for headers in (
            ADMIN,
            TEST_USERS["design_board_headers"],
            make_monitor_headers(MONITOR_USER_ID),
            make_landowner_headers(scenario["landowner"]["id"]),
            make_developer_headers(scenario["developer"]["id"]),
        ):
            validate_error(
                api_client.review_severance_application(app_id, {"decision": "APPROVE"}, headers),
                ApiErrorId.ERR_ROLE_NOT_PERMITTED.value,
            )

        still_in_review = fetch_application(app_id)
        assert still_in_review["status"] == "UNDER_REVIEW", (
            f"every refusal is inert, so the application stays UNDER_REVIEW, "
            f"got {still_in_review['status']}"
        )
        assert still_in_review["version"] == screened["version"], (
            "a refused write may not increment the application version"
        )
        assert still_in_review.get("decided_by_user_id") is None, (
            "a refused decision may not record decided_by_user_id"
        )
        assert still_in_review.get("certified_by_user_id") is None, (
            "a refused certification may not record certified_by_user_id"
        )
        assert still_in_review["allocated_units"] == 0, (
            "no grant may be computed by a refused decision"
        )

    def test_exclusive_writes_refuse_before_path_resolution_while_reads_stay_open(self):
        """Inspection and designation are single-role writes; detail reads are not.

        PRD §2.10: "Authentication precedes authorization, existence precedes ownership, safety precedes constraint, and fiscal checks always come last."
        PRD §2.10: "**Path existence** — every identifier in the path resolves, left to right; otherwise the matching not-found code (404). Applies to every endpoint carrying a path identifier."
        PRD §3.9: "An `EasementMonitor` records an inspection against an easement, supplying `inspection_date`, `finding`, `affected_acres`, and an optional `note`; the acting user is stored as `inspector_user_id`."
        PRD §2.1: "Administrators designate and activate areas, publish appraisal schedules, enroll parcels, certify approved severances, operate the municipal bank's purchase and resale channels, settle and reverse transactions, run program evaluations, drive the logical clock, and run the compliance sweep."
        PRD §2.1: "An `EasementMonitor` is a field monitor who inspects preserved parcels and verifies cures on noticed violations."
        PRD §2.1: "Every role may read every resource through the listing and detail endpoints, with two exceptions noted in the endpoint table: the party listing and the party detail read are not open to all six roles in the same way."

        Design: Corner/rbac/each_exclusive_step_of_the_severance_chain_refuses_every_other_role
        """
        scenario = _filed_severance()

        # Recording an inspection belongs to the monitor.  The easement identifier is
        # deliberately unresolvable: authorization is decided above path existence, so
        # the administrator sees the role refusal rather than a 404.
        validate_error(
            api_client.create_inspection(
                NON_EXISTENT_UUID,
                {"inspection_date": "2026-08-10", "finding": "COMPLIANT", "affected_acres": 0.00},
                ADMIN,
            ),
            ApiErrorId.ERR_ROLE_NOT_PERMITTED.value,
        )

        # Designating an area belongs to the administrator.
        before_areas, before_meta = validate_paginated(
            api_client.list_sending_areas(ADMIN, params={"limit": 100, "offset": 0})
        )
        validate_error(
            api_client.create_sending_area(
                create_sending_area_payload(), make_monitor_headers(MONITOR_USER_ID)
            ),
            ApiErrorId.ERR_ROLE_NOT_PERMITTED.value,
        )
        after_areas, after_meta = validate_paginated(
            api_client.list_sending_areas(ADMIN, params={"limit": 100, "offset": 0})
        )
        assert after_meta["total_count"] == before_meta["total_count"], (
            f"a refused designation must create nothing: {before_meta['total_count']} "
            f"-> {after_meta['total_count']}"
        )

        # The detail read of a severance application is open to all six roles.
        readers = {
            "ProgramAdministrator": ADMIN,
            "SeveranceReviewer": make_reviewer_headers(REVIEWER_USER_ID),
            "DesignReviewBoard": TEST_USERS["design_board_headers"],
            "EasementMonitor": make_monitor_headers(MONITOR_USER_ID),
            "Landowner": make_landowner_headers(scenario["landowner"]["id"]),
            "Developer": make_developer_headers(scenario["developer"]["id"]),
        }
        for role, headers in readers.items():
            seen = validate_success(
                api_client.get_severance_application(scenario["application"]["id"], headers)
            )
            assert seen["id"] == scenario["application"]["id"], (
                f"{role} must be able to read the severance application detail"
            )
            assert seen["status"] == "SUBMITTED", (
                f"{role} reads the same unchanged application, got {seen['status']}"
            )


def _market_ready_certificate() -> dict:
    """A landowner holding a 22-unit certificate out of an UNDERSERVED NB-EAST
    area, with the municipal bank, a developer and an NB-EAST appraisal window
    all in place."""
    scenario = setup_certified_severance()
    scenario["bank"] = register_bank(neighborhood_code="NB-CORE")
    scenario["developer"] = register_developer(neighborhood_code="NB-CORE")
    scenario["schedule"] = publish_appraisal_schedule(
        neighborhood_code=scenario["area"]["neighborhood_code"],
        per_unit_value_cents=SCHEDULE_PER_UNIT_CENTS,
        equity_adjustment_bps=SCHEDULE_EQUITY_BPS,
        effective_from="2026-01-01",
        effective_to="2027-01-01",
    )
    return scenario


class TestChannelRoleAgreement:
    """A market channel may only be opened by the side the channel belongs to."""

    def test_neither_side_may_open_the_other_side_s_channel(self):
        """The selling landowner cannot open a bank channel and the administrator cannot open a private deal.

        PRD §2.1: "Channel-role agreement, rejected with `ERR_CHANNEL_ROLE_MISMATCH` (HTTP 403), requires that a `PRIVATE` market transaction be proposed by the selling side — a `Landowner` or a `Developer` — and that a `BANK_PURCHASE` or `BANK_RESALE` transaction be proposed only by a `ProgramAdministrator`."
        PRD §3.7: "A `PRIVATE` proposal may be filed only by the selling side, a `Landowner` or a `Developer`; the two bank channels may be filed only by a `ProgramAdministrator`; mismatches are rejected with `ERR_CHANNEL_ROLE_MISMATCH`."
        PRD §2.10: "**Channel and role agreement** — as described in §2.1; otherwise `ERR_CHANNEL_ROLE_MISMATCH` (403). Applies to transaction proposal."
        PRD §3.7: "An accepted proposal opens in `status` `PROPOSED`, moves the certificate `HELD → UNDER_CONTRACT`, grows the certificate's `units_encumbered` by the traded `units`, and increments the certificate's `version`."

        Design: Corner/rbac/bank_channels_belong_to_the_administrator_and_private_channels_to_the_seller
        """
        scenario = _market_ready_certificate()
        certificate = scenario["certificate"]
        landowner = scenario["landowner"]
        assert certificate["market_status"] == "HELD", "precondition: the certificate is tradable"

        # The selling landowner is the right owner but the wrong channel authority.
        validate_error(
            api_client.create_market_transaction(
                create_market_transaction_payload(
                    certificate["id"], landowner["id"], scenario["bank"]["id"],
                    units=certificate["units_remaining"], channel="BANK_PURCHASE",
                ),
                make_landowner_headers(landowner["id"]),
            ),
            ApiErrorId.ERR_CHANNEL_ROLE_MISMATCH.value,
        )

        # The administrator runs the bank's channels but may not stand in for the
        # selling side on a negotiated private deal.
        validate_error(
            api_client.create_market_transaction(
                create_market_transaction_payload(
                    certificate["id"], landowner["id"], scenario["developer"]["id"],
                    units=certificate["units_remaining"], channel="PRIVATE",
                    agreed_price_cents=30_000_000,
                ),
                ADMIN,
            ),
            ApiErrorId.ERR_CHANNEL_ROLE_MISMATCH.value,
        )

        unchanged = fetch_certificate(certificate["id"])
        assert unchanged["market_status"] == "HELD", (
            f"a refused proposal may not encumber the certificate, got {unchanged['market_status']}"
        )
        assert unchanged["units_encumbered"] == 0, (
            f"a refused proposal may not grow units_encumbered, got {unchanged['units_encumbered']}"
        )
        assert unchanged["version"] == certificate["version"], (
            "a refused proposal may not increment the certificate version"
        )
        rows, meta = validate_paginated(
            api_client.list_market_transactions(ADMIN, params={"limit": 100, "offset": 0})
        )
        assert meta["total_count"] == 0, (
            f"two refused proposals must persist nothing, got {meta['total_count']} rows"
        )

    def test_the_administrator_opens_the_bank_purchase_at_the_administered_price(self):
        """The same payload the landowner was refused succeeds for the administrator, priced off the schedule.

        PRD §3.7: "`agreed_price_cents` is required and must be greater than zero for `PRIVATE`, and must be omitted for both bank channels, which are priced from the appraisal schedule instead."
        PRD §3.7: "`applied_per_unit_value_cents` is the selected schedule's `per_unit_value_cents` multiplied by one plus its `equity_adjustment_bps` divided by ten thousand, rounded half up to a whole number of cents — the rounding happens on the per-unit figure, before any multiplication by units."
        PRD §3.7: "For `BANK_PURCHASE`, a per-unit price is formed by discounting the equity-adjusted per-unit value by 300 basis points — multiplying it by one minus three hundred divided by ten thousand — and rounding half up to whole cents; `gross_price_cents` is again that per-unit price multiplied by `units`."
        PRD §3.7: "`price_deviation_bps` is the difference between `gross_price_cents` and `appraised_reference_cents`, divided by `appraised_reference_cents`, multiplied by ten thousand, and rounded half up to a whole number of basis points; it is signed, so a below-appraisal deal reports a negative figure."
        PRD §3.7: "The `conveyance_mode` supplied on the proposal is not the authoritative value: the stored `conveyance_mode` remains unset for as long as the transaction is `PROPOSED`, and is pinned by the system at settlement from a comparison of the traded units against the certificate's remaining units."
        PRD §3.7: "`program_fee_cents`, `equity_surcharge_cents`, and `net_to_seller_cents` all stay at 0 until settlement, and `conveyed_certificate_id`, `settled_at`, `reversed_at`, and `reversal_reason` all stay unset."

        Design: Corner/rbac/bank_channels_belong_to_the_administrator_and_private_channels_to_the_seller
        """
        scenario = _market_ready_certificate()
        certificate = scenario["certificate"]
        units = certificate["units_remaining"]
        assert units == CANONICAL_BASELINE_UNITS, f"precondition: 22 units on the certificate, got {units}"

        transaction = validate_success(
            api_client.create_market_transaction(
                create_market_transaction_payload(
                    certificate["id"], scenario["landowner"]["id"], scenario["bank"]["id"],
                    units=units, channel="BANK_PURCHASE",
                ),
                ADMIN,
            ),
            201,
        )
        assert_market_transaction(transaction)
        assert transaction["status"] == "PROPOSED", (
            f"an accepted proposal opens PROPOSED, got {transaction['status']}"
        )
        assert transaction["channel"] == "BANK_PURCHASE", "the channel is echoed as proposed"
        assert transaction.get("agreed_price_cents") is None, (
            "a bank channel carries no agreed price: it is priced from the schedule"
        )
        assert transaction.get("conveyance_mode") is None, (
            "conveyance_mode stays unset while the transaction is PROPOSED"
        )
        assert transaction["applied_neighborhood_code"] == "NB-EAST", (
            "the rights' origin neighborhood selects the schedule"
        )
        assert transaction["applied_per_unit_value_cents"] == ADJUSTED_PER_UNIT_CENTS, (
            f"1234567 corrected by +250 bps rounds half up to {ADJUSTED_PER_UNIT_CENTS}, "
            f"got {transaction['applied_per_unit_value_cents']}"
        )
        assert transaction["appraised_reference_cents"] == ADJUSTED_PER_UNIT_CENTS * units, (
            f"the appraised reference is the per-unit figure times {units} units, "
            f"got {transaction['appraised_reference_cents']}"
        )
        assert transaction["gross_price_cents"] == 27_004_296, (
            "the bank pays 1265431 discounted by 300 bps -> 1227468 per unit, times 22 units, "
            f"got {transaction['gross_price_cents']}"
        )
        assert transaction["price_deviation_bps"] == -300, (
            f"a fixed 300 bps discount reports as -300 bps, got {transaction['price_deviation_bps']}"
        )
        assert transaction["program_fee_cents"] == 0, "no fee accrues before settlement"
        assert transaction["equity_surcharge_cents"] == 0, "no surcharge accrues before settlement"
        assert transaction["net_to_seller_cents"] == 0, "no seller proceeds accrue before settlement"
        assert transaction.get("settled_at") is None, "settled_at stays unset while PROPOSED"

        encumbered = fetch_certificate(certificate["id"])
        assert encumbered["market_status"] == "UNDER_CONTRACT", (
            f"the accepted proposal moves the certificate HELD -> UNDER_CONTRACT, "
            f"got {encumbered['market_status']}"
        )
        assert encumbered["units_encumbered"] == units, (
            f"units_encumbered grows by the traded units, got {encumbered['units_encumbered']}"
        )
        assert encumbered["version"] == certificate["version"] + 1, (
            "the accepted proposal increments the certificate version by exactly one"
        )
        assert encumbered["lifecycle_status"] == "ISSUED", (
            "proposing a deal touches only the tradability dimension"
        )

        rows, meta = validate_paginated(
            api_client.list_market_transactions(
                ADMIN, params={"channel": "BANK_PURCHASE", "limit": 100, "offset": 0}
            )
        )
        assert meta["total_count"] == 1, (
            f"exactly one bank purchase exists, got {meta['total_count']}"
        )
        assert rows[0]["id"] == transaction["id"], "the listing returns the accepted proposal"


class TestCureVerificationSegregationOfDuties:
    """Nobody signs off on the violation they themselves recorded."""

    def test_the_recording_inspector_may_not_verify_their_own_cure(self):
        """Both cure outcomes are refused to the identity stored as inspector_user_id.

        PRD §2.1: "Segregation of duties, rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403), requires that the `X-User-ID` certifying a severance application differ from the `decided_by_user_id` that recorded its approval, and that the `X-User-ID` verifying a cure differ from the `inspector_user_id` that recorded the inspection."
        PRD §3.9: "The inspection must be in `CURE_PENDING` for either outcome, otherwise `ERR_INSPECTION_NOT_CURABLE`, and segregation of duties applies: the verifying user must differ from the `inspector_user_id` who recorded the finding, otherwise `ERR_SEGREGATION_OF_DUTIES`."
        PRD §3.9: "No one signs off on their own inspection."
        PRD §3.9: "`severity_score` is the weighted sum rounded half up to two decimal places, with the rounding applied once to the sum and never to individual terms."
        PRD §3.9: "`cure_deadline` is `inspection_date` advanced by the band's day count, and the same deadline is copied onto the easement."

        Design: Corner/rbac/a_cure_must_be_verified_by_someone_other_than_the_inspector
        """
        scenario = setup_frozen_certificate()
        inspection = scenario["inspection"]
        assert_monitoring_inspection(inspection)
        assert inspection["status"] == "CURE_PENDING", (
            f"a violation finding opens the inspection CURE_PENDING, got {inspection['status']}"
        )
        assert inspection["inspector_user_id"] == MONITOR_USER_ID, (
            "the recording monitor's identity is stored as inspector_user_id"
        )
        assert inspection["severity_score"] == pytest.approx(48.60, abs=0.01), (
            "90 at one half plus a 12.00/100.00 extent at three tenths scores 48.60, "
            f"got {inspection['severity_score']}"
        )
        assert_same_date(inspection["cure_deadline"], "2026-10-09", "cure_deadline")
        assert inspection.get("cure_verified_by_user_id") is None, (
            "no verifier is recorded until a cure is verified"
        )
        assert scenario["easement"]["compliance_status"] == "VIOLATION_NOTICED", (
            "precondition: the easement is out of compliance"
        )
        assert scenario["certificate"]["market_status"] == "FROZEN", (
            "precondition: the derived certificate is frozen"
        )

        for outcome in ("CURED", "CURE_IN_PROGRESS"):
            validate_error(
                api_client.verify_cure(
                    inspection["id"], {"outcome": outcome},
                    make_monitor_headers(MONITOR_USER_ID),
                ),
                ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value,
            )

        after = fetch_inspection(inspection["id"])
        assert after["status"] == "CURE_PENDING", (
            f"a refused verification leaves the inspection CURE_PENDING, got {after['status']}"
        )
        assert after["version"] == inspection["version"], (
            f"a refused verification may not increment the inspection version: "
            f"{inspection['version']} -> {after['version']}"
        )
        assert after.get("cure_verified_at") is None, (
            "a refused verification may not stamp cure_verified_at"
        )
        assert after.get("cure_verified_by_user_id") is None, (
            "a refused verification may not record a verifier"
        )
        assert_same_date(after["cure_deadline"], "2026-10-09", "cure_deadline")
        assert fetch_easement(scenario["easement"]["id"])["compliance_status"] == "VIOLATION_NOTICED", (
            "a refused verification may not move the easement's stewardship dimension"
        )
        assert fetch_certificate(scenario["certificate"]["id"])["market_status"] == "FROZEN", (
            "a refused verification may not thaw the frozen certificate"
        )

    def test_a_second_monitor_and_the_administrator_may_both_verify(self):
        """A different monitor reports progress and the administrator then clears the violation.

        PRD §3.9: "An `EasementMonitor` or `ProgramAdministrator` verifies a cure against the inspection, supplying an `outcome` of `CURED` or `CURE_IN_PROGRESS` and an optional `verification_note`."
        PRD §3.9: "The inspection stays in `CURE_PENDING` and keeps its `cure_deadline`, the easement moves `VIOLATION_NOTICED → UNDER_CURE`, and the deadline is explicitly not extended — a landowner cannot buy time by reporting progress."
        PRD §3.9: "Certificates stay `FROZEN` and redemptions stay `HELD_PENDING_COMPLIANCE`."
        PRD §3.9: "The easement moves to `CURED` from whichever of `VIOLATION_NOTICED`, `UNDER_CURE`, or `ESCALATED` it currently occupies, and its `cure_deadline` is cleared."
        PRD §3.9: "Every certificate on that easement whose `market_status` is `FROZEN` returns to `HELD`."
        PRD §3.9: "The inspection records `cure_verified_at` from the current logical clock and `cure_verified_by_user_id` from the acting user, and moves to `CURED`; the `version` of every entity touched is incremented."
        PRD §3.9: "First the easement's `compliance_status` changes and its `prior_violation_count` increments."

        Design: Corner/rbac/a_cure_must_be_verified_by_someone_other_than_the_inspector
        """
        scenario = setup_frozen_certificate()
        inspection = scenario["inspection"]

        progress = validate_success(
            api_client.verify_cure(
                inspection["id"], {"outcome": "CURE_IN_PROGRESS", "verification_note": "fencing rebuilt"},
                make_monitor_headers(MONITOR_USER_ID_ALT),
            )
        )
        assert progress["status"] == "CURE_PENDING", (
            f"CURE_IN_PROGRESS does not clear the violation, got {progress['status']}"
        )
        assert_same_date(progress["cure_deadline"], "2026-10-09", "cure_deadline")
        under_cure = fetch_easement(scenario["easement"]["id"])
        assert under_cure["compliance_status"] == "UNDER_CURE", (
            f"reported progress moves the easement VIOLATION_NOTICED -> UNDER_CURE, "
            f"got {under_cure['compliance_status']}"
        )
        assert fetch_certificate(scenario["certificate"]["id"])["market_status"] == "FROZEN", (
            "certificates stay frozen while the cure is only in progress"
        )

        cleared = validate_success(
            api_client.verify_cure(
                inspection["id"], {"outcome": "CURED"}, make_admin_headers(ADMIN_USER_ID),
            )
        )
        assert cleared["status"] == "CURED", (
            f"the administrator's verification moves the inspection to CURED, got {cleared['status']}"
        )
        assert cleared["cure_verified_by_user_id"] == ADMIN_USER_ID, (
            "the acting verifier identity is recorded, and it is not the inspector"
        )
        assert cleared["cure_verified_by_user_id"] != cleared["inspector_user_id"], (
            "the verifier and the inspector must be different identities"
        )
        assert_same_instant(cleared["cure_verified_at"], CLOCK, "cure_verified_at")
        assert cleared["version"] > progress["version"], (
            f"the cure verification increments the inspection version: "
            f"{progress['version']} -> {cleared['version']}"
        )
        assert cleared.get("escalated_at") is None, (
            "nothing escalated: escalated_at is only stamped by the compliance sweep"
        )

        easement = fetch_easement(scenario["easement"]["id"])
        assert easement["compliance_status"] == "CURED", (
            f"the compensating cascade moves the easement to CURED, got {easement['compliance_status']}"
        )
        assert easement.get("cure_deadline") is None, (
            "the easement's cure_deadline is cleared by a verified cure"
        )
        assert easement["prior_violation_count"] == 1, (
            f"the noticed violation stays on the easement's history, "
            f"got {easement['prior_violation_count']}"
        )
        assert easement["recording_status"] == "RECORDED", (
            "the register dimension is untouched by stewardship movement"
        )
        thawed = fetch_certificate(scenario["certificate"]["id"])
        assert thawed["market_status"] == "HELD", (
            f"a frozen certificate returns to HELD once the cure is verified, "
            f"got {thawed['market_status']}"
        )
        assert thawed["lifecycle_status"] == "ISSUED", (
            "the rights dimension was never touched by the freeze or the thaw"
        )


class TestSplitOwnership:
    """Landowner and Developer are peers on the split endpoint; only the holder may use it."""

    def test_only_the_holding_party_may_split_although_both_roles_are_authorized(self):
        """A developer is refused the split on ownership even with the right version; the holder succeeds on the identical payload.

        PRD §3.6: "A holder — a `Landowner` or a `Developer` whose identity matches `holder_party_id` — or a `ProgramAdministrator` acting on their behalf may split units off a certificate into a new child."
        PRD §2.1: "The concrete comparisons are: `owner_party_id` on a `SendingParcel`, `applicant_party_id` on a `SeveranceApplication`, `developer_party_id` on a `ReceivingSiteApplication`, `seller_party_id` on a `MarketTransaction` being cancelled, and `holder_party_id` on a `Certificate` being split or retired."
        PRD §2.1: "A failed ownership comparison is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."
        PRD §2.10: "**Ownership** — for an entity-backed role, `X-User-ID` matches the resource's owning party as §2.1 describes; otherwise `ERR_NOT_RESOURCE_OWNER` (403). Applies to severance filing, severance resubmission, receiving-site filing, design resubmission, finalization, redemption allocation, redemption release, certificate split, certificate retirement, and transaction cancellation."
        PRD §2.10: "The checks below form one global ladder, evaluated strictly from the top; the first check that fails decides the response, and no later check is consulted."
        PRD §3.6: "The child certificate is minted with `parent_certificate_id` pointing at the parent, with `conservation_easement_id`, `origin_sending_area_id` and `origin_neighborhood_code` copied down the lineage unchanged, with `holder_party_id` equal to the parent's holder, with `units_face` and `units_remaining` both equal to the requested `units`, with `generation` one higher than the parent's `generation`, with `split_count` at 0, with `lifecycle_status` of `ISSUED` and `market_status` of `HELD`, and with `issued_at` at the current logical clock."
        PRD §3.6: "The source easement's `units_issued_total` and `units_outstanding` are completely unchanged by a split — the rights have moved, not multiplied."
        PRD §2.11: "For any single party, `units_held` is the sum of `units_remaining` across the certificates it holds whose `lifecycle_status` is `ISSUED` or `PARTIALLY_REDEEMED`, and `certificates_held_count` is the count of those same certificates."

        Design: Corner/rbac/peer_roles_share_the_split_endpoint_but_only_the_holder_may_use_it
        """
        scenario = setup_certified_severance()
        developer = register_developer(neighborhood_code="NB-CORE")
        landowner = scenario["landowner"]
        parent = scenario["certificate"]
        assert parent["holder_party_id"] == landowner["id"], "precondition: the landowner holds it"
        assert parent["units_encumbered"] == 0, "precondition: nothing is encumbered"

        # A Developer is on the endpoint's authorized list, so the refusal cannot be a
        # role refusal; it is the ownership comparison against holder_party_id.
        peer_read = validate_success(api_client.get_certificate(parent["id"], make_developer_headers(developer["id"])))
        assert peer_read["id"] == parent["id"], "a peer role may read the certificate it does not hold"

        validate_error(
            api_client.split_certificate(
                parent["id"], split_certificate_payload(8, parent["version"]),
                make_developer_headers(developer["id"]),
            ),
            ApiErrorId.ERR_NOT_RESOURCE_OWNER.value,
        )
        # Ownership sits above the stale-version rung, so a wrong version does not
        # change the answer for a non-holder.
        validate_error(
            api_client.split_certificate(
                parent["id"], split_certificate_payload(8, parent["version"] + 7),
                make_developer_headers(developer["id"]),
            ),
            ApiErrorId.ERR_NOT_RESOURCE_OWNER.value,
        )

        untouched = fetch_certificate(parent["id"])
        assert untouched["units_split_out"] == 0, "a refused split moves no units off the parent"
        assert untouched["units_remaining"] == CANONICAL_BASELINE_UNITS, (
            f"a refused split leaves units_remaining at 22, got {untouched['units_remaining']}"
        )
        assert untouched["split_count"] == 0, "a refused split does not advance split_count"
        assert untouched["version"] == parent["version"], (
            "a refused split may not increment the certificate version"
        )

        child = validate_success(
            api_client.split_certificate(
                parent["id"], split_certificate_payload(8, parent["version"]),
                make_landowner_headers(landowner["id"]),
            ),
            201,
        )
        assert_certificate(child)
        assert child["parent_certificate_id"] == parent["id"], "the child points at its parent"
        assert child["holder_party_id"] == landowner["id"], "the child is minted to the parent's holder"
        assert child["units_face"] == 8 and child["units_remaining"] == 8, (
            f"the child carries the requested 8 units, got face={child['units_face']} "
            f"remaining={child['units_remaining']}"
        )
        assert child["generation"] == parent["generation"] + 1, (
            f"the child's generation is one higher than the parent's, got {child['generation']}"
        )
        assert child["split_count"] == 0, "a fresh child has split no units of its own"
        assert child["serial_number"] == parent["serial_number"] + "-S1", (
            f"the first child's serial appends -S1, got {child['serial_number']}"
        )
        assert child["lifecycle_status"] == "ISSUED", "the child opens ISSUED"
        assert child["market_status"] == "HELD", "the child opens HELD"
        assert child["conservation_easement_id"] == parent["conservation_easement_id"], (
            "the easement link is copied down the lineage unchanged"
        )
        assert child["origin_neighborhood_code"] == parent["origin_neighborhood_code"], (
            "the origin neighborhood is copied down the lineage unchanged"
        )
        assert_same_instant(child["issued_at"], CLOCK, "issued_at")

        after = fetch_certificate(parent["id"])
        assert after["units_split_out"] == 8, f"8 units left the parent, got {after['units_split_out']}"
        assert after["units_remaining"] == 14, (
            f"the parent keeps 22 less 8 units, got {after['units_remaining']}"
        )
        assert after["split_count"] == 1, f"the parent's split_count is 1, got {after['split_count']}"
        assert after["version"] == parent["version"] + 1, (
            "the accepted split increments the parent's version by exactly one"
        )
        assert after["lifecycle_status"] == "ISSUED", "a split is a lineage mutation, not a lifecycle advance"
        assert after["market_status"] == "HELD", "a split leaves the tradability dimension alone"

        easement = fetch_easement(parent["conservation_easement_id"])
        assert_conservation_easement(easement)
        assert easement["units_issued_total"] == CANONICAL_BASELINE_UNITS, (
            f"a split creates no rights, got units_issued_total={easement['units_issued_total']}"
        )
        assert easement["units_outstanding"] == CANONICAL_BASELINE_UNITS, (
            f"a split destroys no rights, got units_outstanding={easement['units_outstanding']}"
        )

        holder = fetch_party(landowner["id"])
        assert_party(holder)
        assert holder["units_held"] == CANONICAL_BASELINE_UNITS, (
            f"the holder still holds 14 plus 8 units, got {holder['units_held']}"
        )
        assert holder["certificates_held_count"] == 2, (
            f"the holder now holds two certificates, got {holder['certificates_held_count']}"
        )
        non_holder = fetch_party(developer["id"])
        assert non_holder["units_held"] == 0, (
            f"the refused developer holds nothing, got {non_holder['units_held']}"
        )
        assert non_holder["certificates_held_count"] == 0, (
            f"the refused developer holds no certificates, got {non_holder['certificates_held_count']}"
        )


def _design_approved_application() -> dict:
    """A developer holding a 22-unit certificate, plus a DESIGN_APPROVED receiving-site
    application on a 12.00-acre site in an area that requires design review."""
    scenario = setup_developer_holding_certificate()
    receiving_area = create_active_receiving_area(
        neighborhood_code="NB-CORE",
        base_density_units_per_acre=4.00,
        max_bonus_pct=0.35,
        absorption_cap_units=500,
        design_review_required=True,
        eligible_sending_area_codes=[],
    )
    filed = file_receiving_site_application(
        scenario["developer"]["id"], receiving_area["id"], 12.00, 20
    )
    scenario.update({
        "receiving_area": receiving_area,
        "filed": filed,
        "rsa": design_decision(filed["id"], "APPROVE"),
    })
    return scenario


class TestStackedRedemptionVersions:
    """Redemptions stack legitimately, so each must pin the version it reasoned about."""

    def test_a_second_allocation_carrying_the_version_the_first_one_spent_is_refused(self):
        """The stale stack trips no state precondition, so only the version pin can catch it.

        PRD §2.8: "Allocating certificate units to back a receiving-site application requires `expected_receiving_site_application_version`, carrying the client's last observed `version` of that `ReceivingSiteApplication`."
        PRD §2.8: "Several redemptions may legitimately be stacked on one application, so a second allocation that carries the version the client read before the first allocation trips no state precondition at all; without this check it would succeed while sizing its units against a backing total that no longer exists."
        PRD §2.8: "If the application's `version` has advanced since the client read it, the allocation is rejected with `ERR_STALE_PARENT_VERSION` (HTTP 412)."
        PRD §3.8: "Second, `base_units` is `site_acres` multiplied by the area's `base_density_units_per_acre`, floored to a whole number."
        PRD §3.8: "Third, `max_bonus_units` is the already-floored `base_units` multiplied by the area's `max_bonus_pct` and then by the tier factor, floored again."
        PRD §3.8: "`required_backing_units` is then the lesser of `requested_bonus_units` and `max_bonus_units` — a developer who asks for more density than the area can grant is not rejected at intake, but is only ever required to back, and can only ever receive, the area's maximum."
        PRD §3.8: "A successful allocation creates a redemption in `ALLOCATED` with `allocated_at` at the current logical clock and `source_easement_id` copied from the certificate's `conservation_easement_id` — the link is copied at allocation time so that later compliance checks can reach the easement directly."
        PRD §3.8: "The certificate's `units_encumbered` grows by `units` and the area's `reserved_units` grows by `units`; nothing is consumed yet, only committed."
        PRD §3.8: "The application's `pending_backed_units` is recomputed, its `version` increments, and a `BACKING_DEFICIENT` application whose backing has been restored to at least `required_backing_units` moves `BACKING_DEFICIENT → DESIGN_APPROVED`."

        Design: Corner/cross_cutting_complexity_layers/stacking_a_second_redemption_on_a_version_the_client_already_spent
        """
        scenario = _design_approved_application()
        rsa = scenario["rsa"]
        developer = scenario["developer"]
        certificate = scenario["certificate"]
        assert_receiving_site_application(rsa)
        assert rsa["status"] == "DESIGN_APPROVED", (
            f"precondition: the board approved the design, got {rsa['status']}"
        )
        assert rsa["base_units"] == 48, f"12.00 acres at 4.00 units per acre floors to 48, got {rsa['base_units']}"
        assert rsa["max_bonus_units"] == 16, (
            f"48 at 0.35 with a 1.00 tier factor floors to 16, got {rsa['max_bonus_units']}"
        )
        assert rsa["required_backing_units"] == 16, (
            f"a 20-unit request is capped at the area's 16, got {rsa['required_backing_units']}"
        )
        assert rsa["pending_backed_units"] == 0, "nothing is backed yet"

        spent_version = rsa["version"]
        first = validate_success(
            api_client.allocate_redemption(
                rsa["id"],
                allocate_redemption_payload(certificate["id"], 10, spent_version),
                make_developer_headers(developer["id"]),
            ),
            201,
        )
        assert_certificate_redemption(first)
        assert first["status"] == "ALLOCATED", f"a fresh allocation opens ALLOCATED, got {first['status']}"
        assert first["units"] == 10, f"10 units were committed, got {first['units']}"
        assert first["source_easement_id"] == certificate["conservation_easement_id"], (
            "the easement link is copied from the certificate at allocation time"
        )
        assert_same_instant(first["allocated_at"], CLOCK, "allocated_at")

        after_first = fetch_receiving_site_application(rsa["id"])
        assert after_first["version"] == spent_version + 1, (
            f"the allocation increments the application version, got {after_first['version']}"
        )
        assert after_first["pending_backed_units"] == 10, (
            f"pending_backed_units is recomputed to 10, got {after_first['pending_backed_units']}"
        )
        assert fetch_certificate(certificate["id"])["units_encumbered"] == 10, (
            "the certificate's units_encumbered grows by the committed units"
        )
        assert fetch_receiving_area(scenario["receiving_area"]["id"])["reserved_units"] == 10, (
            "the area's reserved_units grows by the committed units"
        )

        # A second allocation is entirely legitimate, but this one still carries the
        # version the client read before the first allocation consumed it.
        validate_error(
            api_client.allocate_redemption(
                rsa["id"],
                allocate_redemption_payload(certificate["id"], 6, spent_version),
                make_developer_headers(developer["id"]),
            ),
            ApiErrorId.ERR_STALE_PARENT_VERSION.value,
        )

        inert = fetch_receiving_site_application(rsa["id"])
        assert inert["version"] == after_first["version"], (
            "a refused allocation may not increment the application version"
        )
        assert inert["pending_backed_units"] == 10, (
            f"a refused allocation may not add backing, got {inert['pending_backed_units']}"
        )
        assert fetch_certificate(certificate["id"])["units_encumbered"] == 10, (
            "a refused allocation may not encumber further certificate units"
        )
        assert fetch_receiving_area(scenario["receiving_area"]["id"])["reserved_units"] == 10, (
            "a refused allocation may not reserve further area capacity"
        )
        rows, meta = validate_paginated(
            api_client.list_certificate_redemptions(
                ADMIN,
                params={"receiving_site_application_id": rsa["id"], "limit": 100, "offset": 0},
            )
        )
        assert meta["total_count"] == 1, (
            f"the refused allocation created no redemption row, got {meta['total_count']}"
        )

        # Re-reading the application and retrying with the fresh version succeeds.
        second = validate_success(
            api_client.allocate_redemption(
                rsa["id"],
                allocate_redemption_payload(certificate["id"], 6, inert["version"]),
                make_developer_headers(developer["id"]),
            ),
            201,
        )
        assert second["status"] == "ALLOCATED", "the retry on a fresh version is accepted"
        assert second["id"] != first["id"], "the retry creates a second, distinct redemption"
        stacked = fetch_receiving_site_application(rsa["id"])
        assert stacked["pending_backed_units"] == 16, (
            f"the two stacked redemptions back 16 units, got {stacked['pending_backed_units']}"
        )
        assert stacked["version"] == inert["version"] + 1, (
            "the accepted retry increments the application version by exactly one"
        )
        assert fetch_certificate(certificate["id"])["units_encumbered"] == 16, (
            "both commitments sit in the certificate's units_encumbered"
        )

    def test_a_version_read_before_the_design_decision_is_equally_stale(self):
        """Any intervening write to the application invalidates the client's pin, not only another allocation.

        PRD §2.8: "In all three cases the version field is a required, non-optional input, and a mismatch against the parent's current `version` is rejected with `ERR_STALE_PARENT_VERSION` (HTTP 412)."
        PRD §3.8: "The supplied version must match the application's current `version`, otherwise `ERR_STALE_PARENT_VERSION`."
        PRD §3.8: "`APPROVE` moves it `DESIGN_REVIEW → DESIGN_APPROVED`."
        PRD §3.8: "Every decision sets `design_reviewed_by_user_id` to the acting user and increments the application's `version`."
        PRD §2.11: "Splitting a certificate, allocating a redemption and releasing a redemption must each leave both `units_issued_total` and `units_outstanding` completely unchanged; only confirmation of a redemption and retirement of units may move `units_outstanding`, and each moves it downward by exactly the units involved."

        Design: Corner/cross_cutting_complexity_layers/stacking_a_second_redemption_on_a_version_the_client_already_spent
        """
        scenario = _design_approved_application()
        rsa = scenario["rsa"]
        filed_version = scenario["filed"]["version"]
        assert rsa["version"] == filed_version + 1, (
            f"the design decision advanced the application past the version the developer "
            f"read at intake: {filed_version} -> {rsa['version']}"
        )

        for stale_version in (filed_version, rsa["version"] + 1, 99):
            validate_error(
                api_client.allocate_redemption(
                    rsa["id"],
                    allocate_redemption_payload(scenario["certificate"]["id"], 5, stale_version),
                    make_developer_headers(scenario["developer"]["id"]),
                ),
                ApiErrorId.ERR_STALE_PARENT_VERSION.value,
            )

        easement = fetch_easement(scenario["certificate"]["conservation_easement_id"])
        assert easement["units_issued_total"] == CANONICAL_BASELINE_UNITS, (
            "refused allocations leave the easement's issuance total alone"
        )
        assert easement["units_outstanding"] == CANONICAL_BASELINE_UNITS, (
            f"refused allocations leave units_outstanding alone, got {easement['units_outstanding']}"
        )
        assert easement["units_redeemed_confirmed"] == 0, "nothing has been confirmed"

        accepted = validate_success(
            api_client.allocate_redemption(
                rsa["id"],
                allocate_redemption_payload(scenario["certificate"]["id"], 5, rsa["version"]),
                make_developer_headers(scenario["developer"]["id"]),
            ),
            201,
        )
        assert accepted["units"] == 5, "the live version is accepted for the same payload"
        after = fetch_easement(scenario["certificate"]["conservation_easement_id"])
        assert after["units_outstanding"] == CANONICAL_BASELINE_UNITS, (
            f"an accepted allocation still moves no rights, got {after['units_outstanding']}"
        )


class TestRepeatedSplitVersions:
    """A certificate may be split repeatedly, so each split must pin the version it read."""

    def test_a_second_split_on_the_version_the_first_split_consumed_is_refused(self):
        """The stale split passes every state precondition, so only the version pin stops it — and the serial run leaves no gap.

        PRD §2.8: "Splitting a certificate requires `expected_certificate_version`, carrying the client's last observed `version` of that `Certificate`."
        PRD §2.8: "A certificate may legitimately be split repeatedly, so a split carrying a superseded version passes every state precondition while reasoning about a `units_remaining` figure the registry has already changed."
        PRD §2.8: "If the certificate's `version` has advanced since the client read it, the split is rejected with `ERR_STALE_PARENT_VERSION` (HTTP 412)."
        PRD §2.10: "**Stale parent version** — the supplied expected version matches the parent's current `version` as §2.8 describes; otherwise `ERR_STALE_PARENT_VERSION` (412). Applies to redemption allocation, certificate split, and party account actions."
        PRD §3.6: "The parent's `split_count` is incremented by one, and the child's `serial_number` is the parent's `serial_number` followed by `-S` and the parent's `split_count` after that increment — so the second child of `TDR-SND-01-00001` is serialized `TDR-SND-01-00001-S2`."
        PRD §3.6: "On the parent, `units_split_out` grows by `units` and `units_remaining` is recomputed, but `lifecycle_status` and `market_status` are both left exactly where they were: a split is a lineage mutation, not a lifecycle advance, which is why the parent's rights dimension can stay `ISSUED` across an arbitrary number of splits."
        PRD §2.11: "For any single certificate, `units_remaining` equals `units_face` less `units_split_out` less `units_redeemed` less `units_retired`, and `units_encumbered` never exceeds `units_remaining`."
        PRD §3.6: "The source easement's `units_issued_total` and `units_outstanding` are completely unchanged by a split — the rights have moved, not multiplied."

        Design: Corner/cross_cutting_complexity_layers/a_second_split_on_the_version_the_first_split_consumed
        """
        scenario = setup_certified_severance()
        landowner = scenario["landowner"]
        parent = scenario["certificate"]
        holder_headers = make_landowner_headers(landowner["id"])
        spent_version = parent["version"]
        easement_id = parent["conservation_easement_id"]

        first_child = validate_success(
            api_client.split_certificate(
                parent["id"], split_certificate_payload(5, spent_version), holder_headers
            ),
            201,
        )
        assert first_child["serial_number"] == parent["serial_number"] + "-S1", (
            f"the first child is serialized -S1, got {first_child['serial_number']}"
        )
        after_first = fetch_certificate(parent["id"])
        assert after_first["version"] == spent_version + 1, (
            f"the first split consumed version {spent_version}, got {after_first['version']}"
        )
        assert after_first["units_remaining"] == 17, (
            f"22 less 5 units remain on the parent, got {after_first['units_remaining']}"
        )
        assert after_first["split_count"] == 1, f"split_count is 1, got {after_first['split_count']}"

        # A further split is legitimate; this one reasons about the pre-split
        # units_remaining figure of 22 that the registry has already changed.
        validate_error(
            api_client.split_certificate(
                parent["id"], split_certificate_payload(4, spent_version), holder_headers
            ),
            ApiErrorId.ERR_STALE_PARENT_VERSION.value,
        )

        inert = fetch_certificate(parent["id"])
        assert inert["version"] == after_first["version"], (
            "a refused split may not increment the parent's version"
        )
        assert inert["split_count"] == 1, (
            f"a refused split may not advance split_count, got {inert['split_count']}"
        )
        assert inert["units_split_out"] == 5, (
            f"a refused split may not move units off the parent, got {inert['units_split_out']}"
        )
        assert inert["units_remaining"] == 17, (
            f"a refused split may not change units_remaining, got {inert['units_remaining']}"
        )
        assert inert["lifecycle_status"] == "ISSUED", "the parent's rights dimension is untouched"
        assert inert["market_status"] == "HELD", "the parent's tradability dimension is untouched"
        children, meta = validate_paginated(
            api_client.list_certificates(
                ADMIN, params={"parent_certificate_id": parent["id"], "limit": 100, "offset": 0}
            )
        )
        assert meta["total_count"] == 1, (
            f"the refused split minted no child, got {meta['total_count']} children"
        )

        second_child = validate_success(
            api_client.split_certificate(
                parent["id"], split_certificate_payload(4, inert["version"]), holder_headers
            ),
            201,
        )
        assert second_child["serial_number"] == parent["serial_number"] + "-S2", (
            f"the refused attempt burned no serial: the second child is -S2, "
            f"got {second_child['serial_number']}"
        )
        assert second_child["units_face"] == 4 and second_child["units_remaining"] == 4, (
            "the second child carries the four requested units"
        )
        assert second_child["generation"] == 2, (
            f"both children are one generation below the root, got {second_child['generation']}"
        )
        after_second = fetch_certificate(parent["id"])
        assert after_second["split_count"] == 2, (
            f"the parent has now split twice, got {after_second['split_count']}"
        )
        assert after_second["units_split_out"] == 9, (
            f"5 plus 4 units have left the parent, got {after_second['units_split_out']}"
        )
        assert after_second["units_remaining"] == 13, (
            f"units_remaining is 22 less 9, got {after_second['units_remaining']}"
        )
        assert after_second["units_remaining"] == (
            after_second["units_face"] - after_second["units_split_out"]
            - after_second["units_redeemed"] - after_second["units_retired"]
        ), "the certificate's unit identity must hold exactly"

        easement = fetch_easement(easement_id)
        assert easement["units_issued_total"] == CANONICAL_BASELINE_UNITS, (
            f"two splits create no rights, got {easement['units_issued_total']}"
        )
        assert easement["units_outstanding"] == CANONICAL_BASELINE_UNITS, (
            f"two splits destroy no rights, got {easement['units_outstanding']}"
        )
        holder = fetch_party(landowner["id"])
        assert holder["units_held"] == CANONICAL_BASELINE_UNITS, (
            f"the holder still holds 13 plus 5 plus 4 units, got {holder['units_held']}"
        )
        assert holder["certificates_held_count"] == 3, (
            f"the holder now holds three certificates, got {holder['certificates_held_count']}"
        )


class TestAccountActionVersionAndFunds:
    """A refused account action leaves the party's version exactly where it was."""

    def test_a_stale_debit_is_refused_before_the_funds_check_and_neither_refusal_burns_the_version(self):
        """412 outranks 402, and a party version is spent only by an action that actually applies.

        PRD §2.8: "An administrative account action against a party requires `expected_party_version`, carrying the client's last observed `version` of that `Party`."
        PRD §2.8: "Repeated credits, debits, suspensions and reinstatements against one party are entirely legitimate, so without this check a debit carrying a superseded version would apply on top of a balance the operator never saw."
        PRD §2.8: "If the party's `version` has advanced since the client read it, the account action is rejected with `ERR_STALE_PARENT_VERSION` (HTTP 412)."
        PRD §2.10: "**Stale parent version** — the supplied expected version matches the parent's current `version` as §2.8 describes; otherwise `ERR_STALE_PARENT_VERSION` (412). Applies to redemption allocation, certificate split, and party account actions."
        PRD §2.10: "**Funds** — at settlement the buyer's `cash_balance_cents` is at least `gross_price_cents`; at reversal the seller's `cash_balance_cents` is at least `net_to_seller_cents` and the municipal bank's `fee_revenue_cents` is at least `program_fee_cents` plus `equity_surcharge_cents`; and a debit account action may not drive a balance below zero. A failure is `ERR_INSUFFICIENT_FUNDS` (402). Applies to settlement, reversal, and party account actions."
        PRD §3.1: "A `CREDIT` adds `amount_cents` to `cash_balance_cents`; a `DEBIT` subtracts it, and is rejected with `ERR_INSUFFICIENT_FUNDS` when the resulting balance would be negative."
        PRD §3.1: "Every one of the four actions increments `Party.version` by one, and — per §2.4 — nothing else in the program does."
        PRD §2.4: "A `Party`'s `version` is incremented **only** by an administrative account action."

        Design: Corner/cross_cutting_complexity_layers/a_rejected_debit_does_not_consume_the_party_version
        """
        set_clock(CLOCK)
        party = register_landowner()
        assert party["version"] == 1, f"a fresh party opens at version 1, got {party['version']}"
        assert party["cash_balance_cents"] == 0, "a fresh party opens with no cash"

        credited = validate_success(
            api_client.party_account_action(
                party["id"],
                account_action_payload("CREDIT", 1, amount_cents=5_000_000, note="opening float"),
                ADMIN,
            )
        )
        assert_party(credited)
        assert credited["cash_balance_cents"] == 5_000_000, (
            f"the credit adds 5000000 cents, got {credited['cash_balance_cents']}"
        )
        assert credited["version"] == 2, (
            f"the accepted action increments the party version to 2, got {credited['version']}"
        )

        # The operator still holds the version it read before the credit.  The debit it
        # is about to attempt is also unaffordable, but the version rung is the higher one.
        validate_error(
            api_client.party_account_action(
                party["id"], account_action_payload("DEBIT", 1, amount_cents=9_000_000), ADMIN
            ),
            ApiErrorId.ERR_STALE_PARENT_VERSION.value,
        )
        after_stale = fetch_party(party["id"])
        assert after_stale["version"] == 2, (
            f"a stale action may not consume the party version, got {after_stale['version']}"
        )
        assert after_stale["cash_balance_cents"] == 5_000_000, (
            f"a stale action moves no cash, got {after_stale['cash_balance_cents']}"
        )

        # With the live version, the same debit is now judged on affordability alone.
        validate_error(
            api_client.party_account_action(
                party["id"], account_action_payload("DEBIT", 2, amount_cents=9_000_000), ADMIN
            ),
            ApiErrorId.ERR_INSUFFICIENT_FUNDS.value,
        )
        after_refused_debit = fetch_party(party["id"])
        assert after_refused_debit["version"] == 2, (
            f"a refused debit does not consume the party version, got {after_refused_debit['version']}"
        )
        assert after_refused_debit["cash_balance_cents"] == 5_000_000, (
            f"a refused debit is not clamped to zero, got {after_refused_debit['cash_balance_cents']}"
        )
        assert after_refused_debit["status"] == "ACTIVE", "a refused debit changes no standing"

        # The version the operator read is therefore still valid for the affordable debit.
        debited = validate_success(
            api_client.party_account_action(
                party["id"], account_action_payload("DEBIT", 2, amount_cents=5_000_000), ADMIN
            )
        )
        assert debited["cash_balance_cents"] == 0, (
            f"the affordable debit empties the balance, got {debited['cash_balance_cents']}"
        )
        assert debited["version"] == 3, (
            f"only the applied action advances the version, got {debited['version']}"
        )

    def test_a_malformed_account_action_is_refused_ahead_of_the_version_check(self):
        """The shape rung sits above the version rung, and no malformed attempt burns a version.

        PRD §2.10: "**Request shape** — every required input field is present; types, enum membership, string lengths, decimal places and numeric ranges are honoured; `period_start` is not after `period_end`; `effective_from` is strictly before `effective_to`; any `units` figure is greater than zero; every field whose name ends in `_cents` is a non-negative integer; unknown fields are ignored rather than rejected. A failure here is `ERR_INVALID_REQUEST` (400). Applies to every endpoint with a request body or query parameters."
        PRD §3.1: "`amount_cents` is required for `CREDIT` and for `DEBIT`, and must be omitted for `SUSPEND` and `REINSTATE`; supplying it in the wrong combination is a malformed request."
        PRD §2.8: "In all three cases the version field is a required, non-optional input, and a mismatch against the parent's current `version` is rejected with `ERR_STALE_PARENT_VERSION` (HTTP 412)."
        PRD §3.1: "A `SUSPEND` sets `status` to `SUSPENDED`; a `REINSTATE` restores `status` to `ACTIVE`."
        PRD §3.1: "Every one of the four actions increments `Party.version` by one, and — per §2.4 — nothing else in the program does."

        Design: Corner/cross_cutting_complexity_layers/a_rejected_debit_does_not_consume_the_party_version
        """
        set_clock(CLOCK)
        party = register_landowner()

        malformed = [
            # amount_cents must be omitted for SUSPEND — and the stale version below it
            # is never reached, because the shape rung decides first.
            {"action": "SUSPEND", "expected_party_version": 99, "amount_cents": 1_000},
            {"action": "REINSTATE", "expected_party_version": 1, "amount_cents": 1_000},
            # amount_cents is required for CREDIT and DEBIT.
            {"action": "CREDIT", "expected_party_version": 1},
            {"action": "DEBIT", "expected_party_version": 1},
            # expected_party_version is required, not optional.
            {"action": "CREDIT", "amount_cents": 1_000},
            {"action": "SUSPEND"},
        ]
        for payload in malformed:
            validate_error(
                api_client.party_account_action(party["id"], payload, ADMIN),
                ApiErrorId.ERR_INVALID_REQUEST.value,
            )

        unchanged = fetch_party(party["id"])
        assert unchanged["version"] == 1, (
            f"no malformed attempt may consume the party version, got {unchanged['version']}"
        )
        assert unchanged["cash_balance_cents"] == 0, "no malformed attempt moves cash"
        assert unchanged["status"] == "ACTIVE", "no malformed attempt changes standing"

        suspended = validate_success(
            api_client.party_account_action(
                party["id"], account_action_payload("SUSPEND", 1), ADMIN
            )
        )
        assert suspended["status"] == "SUSPENDED", (
            f"a well-formed SUSPEND takes effect, got {suspended['status']}"
        )
        assert suspended["version"] == 2, (
            f"the version the malformed attempts left alone is still valid, got {suspended['version']}"
        )
        assert suspended["cash_balance_cents"] == 0, "suspension moves no cash"

        reinstated = validate_success(
            api_client.party_account_action(
                party["id"], account_action_payload("REINSTATE", 2), ADMIN
            )
        )
        assert reinstated["status"] == "ACTIVE", (
            f"a well-formed REINSTATE restores standing, got {reinstated['status']}"
        )
        assert reinstated["version"] == 3, (
            f"each applied action increments the version by exactly one, got {reinstated['version']}"
        )


class TestHoldingsReconciliation:
    """The denormalized holdings counters must agree with their definitions after every step."""

    def test_holdings_counters_reconcile_across_issuance_split_sale_and_retirement(self):
        """One certificate is issued, split, half sold and the rest retired; every counter is checked at each step.

        PRD §2.7: "Derived totals are reconciled, not accumulated blindly."
        PRD §2.11: "For any single party, `units_held` is the sum of `units_remaining` across the certificates it holds whose `lifecycle_status` is `ISSUED` or `PARTIALLY_REDEEMED`, and `certificates_held_count` is the count of those same certificates."
        PRD §2.11: "For any single easement, `units_issued_total` equals `units_redeemed_confirmed` plus `units_retired` plus `units_outstanding` — equivalently, `units_outstanding` is the total face value of the root issuances backed by that easement, less everything redeemed and everything retired across the easement's entire certificate lineage including every split child."
        PRD §2.11: "The program has no external source or sink of money."
        PRD §2.11: "Summed across every `Party`, `cash_balance_cents` plus `fee_revenue_cents` is a constant."
        PRD §3.1: "`units_held` and `certificates_held_count` are reconciled read models, recomputed from the registry whenever a certification, settlement, reversal or retirement changes what the party holds, exactly as §2.11 defines them."
        PRD §2.4: "Cash movement driven by a settlement or a reversal, and recomputation of `units_held` or `certificates_held_count` driven by any cascade, both leave `Party.version` untouched, so an operator's observed party version remains valid across all of them."
        PRD §3.7: "First, a fee rate is selected by tier from `gross_price_cents` itself, never from any post-surcharge figure: a gross of at most 5,000,000 cents — fifty thousand dollars — attracts 350 basis points; a gross above that but at most 25,000,000 cents — two hundred fifty thousand dollars — attracts 275 basis points; anything above that attracts 200 basis points."
        PRD §3.7: "Third, `equity_surcharge_cents` is `gross_price_cents` multiplied by a surcharge rate divided by ten thousand, rounded half up to whole cents, where the surcharge rate comes from the `equity_tier` of the sending area named by the certificate's `origin_sending_area_id`: 150 basis points for `HIGH_VALUE`, 75 basis points for `MODERATE`, and 0 basis points for `UNDERSERVED`, so preserving land in an underserved neighborhood carries no surcharge at all."
        PRD §3.7: "Fourth, `net_to_seller_cents` is `gross_price_cents` less `program_fee_cents` less `equity_surcharge_cents`."
        PRD §3.7: "When the traded `units` equal the certificate's `units_remaining`, `conveyance_mode` is pinned to `WHOLE`: the certificate itself changes hands, its `holder_party_id` becomes `buyer_party_id`, and `conveyed_certificate_id` is set to the traded `certificate_id`."
        PRD §3.6: "`units_retired` grows by `units` and `units_remaining` is recomputed; when `units_remaining` reaches zero the `lifecycle_status` becomes `RETIRED`, and it does so even if redemption also contributed to emptying the certificate — retirement outranks redemption when both reduced the same certificate to zero."
        PRD §3.6: "A `RETIREMENT` chain-of-title row is appended with no transferee and no price, the backing easement's `units_retired` and `units_outstanding` are recomputed (leaving `units_issued_total` untouched), the holder's `units_held` and `certificates_held_count` are recomputed, and the certificate's `version` is incremented."

        Design: Corner/cross_cutting_complexity_layers/holdings_counters_reconcile_across_issuance_split_sale_and_retirement
        """
        scenario = setup_certified_severance()
        landowner = scenario["landowner"]
        parent = scenario["certificate"]
        easement_id = parent["conservation_easement_id"]
        holder_headers = make_landowner_headers(landowner["id"])
        developer = register_developer(neighborhood_code="NB-CORE")
        bank = register_bank(neighborhood_code="NB-CORE")
        publish_appraisal_schedule(
            neighborhood_code=scenario["area"]["neighborhood_code"],
            per_unit_value_cents=SCHEDULE_PER_UNIT_CENTS,
            equity_adjustment_bps=SCHEDULE_EQUITY_BPS,
            effective_from="2026-01-01",
            effective_to="2027-01-01",
        )
        credit_party(developer["id"], 10_000_000)
        cash_before = program_cash_total_now()
        landowner_version_before = fetch_party(landowner["id"])["version"]
        developer_version_before = fetch_party(developer["id"])["version"]

        # Step one — issuance.
        seller = fetch_party(landowner["id"])
        assert seller["units_held"] == CANONICAL_BASELINE_UNITS, (
            f"the applicant holds the whole issuance, got {seller['units_held']}"
        )
        assert seller["certificates_held_count"] == 1, (
            f"one certificate was minted, got {seller['certificates_held_count']}"
        )
        issued_easement = fetch_easement(easement_id)
        assert issued_easement["units_issued_total"] == CANONICAL_BASELINE_UNITS
        assert issued_easement["units_outstanding"] == CANONICAL_BASELINE_UNITS
        assert issued_easement["units_redeemed_confirmed"] == 0
        assert issued_easement["units_retired"] == 0

        # Step two — a split of 8 units keeps the holder's totals identical.
        child = validate_success(
            api_client.split_certificate(
                parent["id"], split_certificate_payload(8, parent["version"]), holder_headers
            ),
            201,
        )
        after_split = fetch_party(landowner["id"])
        assert after_split["units_held"] == CANONICAL_BASELINE_UNITS, (
            f"a split moves rights without creating them, got {after_split['units_held']}"
        )
        assert after_split["certificates_held_count"] == 2, (
            f"the holder now holds two certificates, got {after_split['certificates_held_count']}"
        )

        # Step three — the child is sold whole to the developer.
        transaction = validate_success(
            api_client.create_market_transaction(
                create_market_transaction_payload(
                    child["id"], landowner["id"], developer["id"], units=8,
                    channel="PRIVATE", agreed_price_cents=10_000_000,
                ),
                holder_headers,
            ),
            201,
        )
        assert transaction["appraised_reference_cents"] == ADJUSTED_PER_UNIT_CENTS * 8, (
            f"the 8-unit appraised reference is {ADJUSTED_PER_UNIT_CENTS * 8}, "
            f"got {transaction['appraised_reference_cents']}"
        )
        assert transaction["price_deviation_bps"] == -122, (
            f"10000000 against a 10123448 reference is -122 bps, got {transaction['price_deviation_bps']}"
        )
        settled = validate_success(
            api_client.settle_market_transaction(transaction["id"], ADMIN, {}))
        assert settled["status"] == "SETTLED", f"the deal settles, got {settled['status']}"
        assert settled["conveyance_mode"] == "WHOLE", (
            f"8 traded units equal the child's units_remaining, got {settled['conveyance_mode']}"
        )
        assert settled["conveyed_certificate_id"] == child["id"], (
            "a whole conveyance hands over the traded certificate itself"
        )
        assert settled["gross_price_cents"] == 10_000_000, "the private gross is the agreed price"
        assert settled["program_fee_cents"] == 275_000, (
            f"a 10000000 gross sits in the 275 bps tier, got {settled['program_fee_cents']}"
        )
        assert settled["equity_surcharge_cents"] == 0, (
            f"an UNDERSERVED sending area carries no surcharge, got {settled['equity_surcharge_cents']}"
        )
        assert settled["net_to_seller_cents"] == 9_725_000, (
            f"10000000 less 275000 less 0 is 9725000, got {settled['net_to_seller_cents']}"
        )

        seller_after = fetch_party(landowner["id"])
        buyer_after = fetch_party(developer["id"])
        bank_after = fetch_party(bank["id"])
        assert seller_after["units_held"] == 14, (
            f"the seller keeps only the 14-unit parent, got {seller_after['units_held']}"
        )
        assert seller_after["certificates_held_count"] == 1, (
            f"the seller holds one certificate again, got {seller_after['certificates_held_count']}"
        )
        assert buyer_after["units_held"] == 8, (
            f"the buyer holds the conveyed 8 units, got {buyer_after['units_held']}"
        )
        assert buyer_after["certificates_held_count"] == 1, (
            f"the buyer holds one certificate, got {buyer_after['certificates_held_count']}"
        )
        assert seller_after["cash_balance_cents"] == 9_725_000, (
            f"the seller receives the net proceeds, got {seller_after['cash_balance_cents']}"
        )
        assert buyer_after["cash_balance_cents"] == 0, (
            f"the buyer pays the whole gross, got {buyer_after['cash_balance_cents']}"
        )
        assert bank_after["fee_revenue_cents"] == 275_000, (
            f"the bank accrues the fee plus the surcharge, got {bank_after['fee_revenue_cents']}"
        )
        assert seller_after["version"] == landowner_version_before, (
            "a settlement leaves Party.version untouched for the seller"
        )
        assert buyer_after["version"] == developer_version_before, (
            "a settlement leaves Party.version untouched for the buyer"
        )
        assert program_cash_total_now() == cash_before, (
            "the three settlement legs sum to zero across the program"
        )

        # Step four — the seller retires everything it still holds.
        retired = validate_success(
            api_client.retire_certificate_units(
                parent["id"], retire_certificate_payload(14, reason="permanent preservation"),
                holder_headers,
            )
        )
        assert retired["units_retired"] == 14, (
            f"14 units were extinguished, got {retired['units_retired']}"
        )
        assert retired["units_remaining"] == 0, (
            f"nothing remains on the parent, got {retired['units_remaining']}"
        )
        assert retired["lifecycle_status"] == "RETIRED", (
            f"an emptied certificate becomes RETIRED, got {retired['lifecycle_status']}"
        )

        final_seller = fetch_party(landowner["id"])
        assert final_seller["units_held"] == 0, (
            f"a RETIRED certificate contributes nothing to units_held, got {final_seller['units_held']}"
        )
        assert final_seller["certificates_held_count"] == 0, (
            f"nor to certificates_held_count, got {final_seller['certificates_held_count']}"
        )
        final_easement = fetch_easement(easement_id)
        assert final_easement["units_issued_total"] == CANONICAL_BASELINE_UNITS, (
            f"retirement leaves the issuance total untouched, got {final_easement['units_issued_total']}"
        )
        assert final_easement["units_retired"] == 14, (
            f"the easement records the retirement, got {final_easement['units_retired']}"
        )
        assert final_easement["units_outstanding"] == 8, (
            f"only the sold 8 units remain outstanding, got {final_easement['units_outstanding']}"
        )
        assert final_easement["units_issued_total"] == (
            final_easement["units_redeemed_confirmed"] + final_easement["units_retired"]
            + final_easement["units_outstanding"]
        ), "the easement's unit identity must hold exactly"
        assert program_cash_total_now() == cash_before, (
            "retiring rights moves no money at all"
        )

        parent_rows, parent_meta = validate_paginated(
            api_client.list_certificate_transfers(
                ADMIN, params={"certificate_id": parent["id"], "limit": 100, "offset": 0}
            )
        )
        assert [row["transfer_type"] for row in parent_rows] == ["ISSUANCE", "SPLIT_OUT", "RETIREMENT"], (
            f"the parent's chain of title records issuance, split and retirement, "
            f"got {[row['transfer_type'] for row in parent_rows]}"
        )
        assert [row["seq_no"] for row in parent_rows] == [1, 2, 3], (
            f"seq_no starts at 1 and increases by one, got {[row['seq_no'] for row in parent_rows]}"
        )
        assert_certificate_transfer(parent_rows[-1])
        assert parent_rows[-1].get("to_party_id") is None, "a retirement has no transferee"
        assert parent_rows[-1].get("price_cents") is None, "a retirement has no price"
        child_rows, child_meta = validate_paginated(
            api_client.list_certificate_transfers(
                ADMIN, params={"certificate_id": child["id"], "limit": 100, "offset": 0}
            )
        )
        assert [row["transfer_type"] for row in child_rows] == ["ISSUANCE", "PRIVATE_SALE"], (
            f"the child's chain of title records its mint and its sale, "
            f"got {[row['transfer_type'] for row in child_rows]}"
        )
        assert child_rows[-1]["price_cents"] == 10_000_000, (
            f"the sale row carries the gross price, got {child_rows[-1]['price_cents']}"
        )


def _approved_severance() -> dict:
    """Clock, landowner, ACTIVE area, canonical parcel and an APPROVED severance
    application ready to certify."""
    set_clock(CLOCK)
    landowner = register_landowner(neighborhood_code="NB-EAST")
    area = create_active_sending_area(**AREA_KWARGS)
    parcel = enroll_parcel(landowner["id"], area["id"], **CANONICAL_PARCEL)
    application = approve_application(parcel["id"], landowner["id"], CANONICAL_BASELINE_UNITS)
    return {
        "landowner": landowner,
        "area": area,
        "parcel": parcel,
        "application": application,
    }


class TestImmediateCascadeVisibility:
    """A read taken immediately after a write observes the fully settled state."""

    def test_the_whole_certification_cascade_is_readable_the_instant_the_response_returns(self):
        """One certification rewrites six entities, and every one of them is already settled on the next read.

        PRD §2.7: "When it does, the whole cascade is part of that request: it is applied before the response is returned, in the order the workflow narrative gives, and every entity it touches has its `version` incremented by one and its `updated_at` refreshed."
        PRD §2.7: "There is no deferred reconciliation and no eventual convergence — a read taken immediately after a write observes the fully settled state."
        PRD §3.5: "The request then moves the application `APPROVED → CERTIFIED`, writes the acting `X-User-ID` into `certified_by_user_id`, increments the application's `version`, and runs a four-link cascade in order."
        PRD §3.5: "That easement is born in `recording_status` `PENDING_RECORDING` and immediately advanced `PENDING_RECORDING → RECORDED` within the same request: `recorded_at` is set to the current logical clock and `recording_reference` is minted deterministically as `EAS-` followed by the parcel's `apn`, a hyphen, and the number 1."
        PRD §3.5: "The easement's `restricted_acres` is recomputed as the parcel's `gross_acres` multiplied by the cumulative severed unit count and divided by the parcel's `baseline_allocation_units`, rounded half up to two decimal places, where the cumulative severed count is the parcel's `severed_units` before this certification plus the `allocated_units` now being certified."
        PRD §3.5: "The easement's `permitted_residual_units` — the buildable envelope left on the preserved parcel — is recomputed as the parcel's `existing_dwelling_units` plus the parcel's `baseline_allocation_units` less that same cumulative severed count."
        PRD §3.5: "On the parcel itself, `easement_status` becomes `RECORDED`, `restricted_acres` is set to match the easement's figure, `severed_units` grows by `allocated_units`, `remaining_units` is reduced by the same amount, and `parcel_status` becomes `PARTIALLY_SEVERED` when `remaining_units` is still above zero or `FULLY_SEVERED` when it has reached zero."
        PRD §3.5: "The sending area's `severed_units_total` is recomputed as the sum of `allocated_units` over every `CERTIFIED` application on parcels in the area, and its `issued_certificate_count` is incremented by one."
        PRD §3.5: "`serial_number` is minted deterministically as `TDR-`, the area's `code`, a hyphen, and the area's `issued_certificate_count` after its increment rendered as five digits with leading zeros — so the first certificate out of an area coded `SND-01` is `TDR-SND-01-00001`."
        PRD §3.5: "The registry's chain of title opens at the same moment: a **CertificateTransfer** row is appended for the new certificate with `transfer_type` of `ISSUANCE`, `seq_no` of 1, `from_party_id` unset, `to_party_id` set to the applicant, `units` equal to `allocated_units`, `price_cents` unset, `market_transaction_id` unset, and `recorded_at` at the current logical clock."
        PRD §3.5: "Finally, the applicant party's `units_held` and `certificates_held_count` are recomputed."
        PRD §2.3: "Filters on a listing narrow the matched set before pagination and before `total_count` is computed."

        Design: Corner/consistency_model/every_cascade_effect_is_readable_the_instant_the_response_returns
        """
        scenario = _approved_severance()
        approved = scenario["application"]
        area_code = scenario["area"]["code"]
        apn = scenario["parcel"]["apn"]
        assert approved["status"] == "APPROVED", f"precondition: APPROVED, got {approved['status']}"
        assert approved["allocated_units"] == CANONICAL_BASELINE_UNITS, (
            f"precondition: the whole 22-unit baseline was granted, got {approved['allocated_units']}"
        )

        certificate = validate_success(
            api_client.certify_severance_application(
                approved["id"], make_admin_headers(ADMIN_USER_ID),
                {"recording_note": "easement recorded at the county"},
            ),
            201,
        )
        assert_certificate(certificate)
        assert certificate["serial_number"] == f"TDR-{area_code}-00001", (
            f"the area's first certificate is serialized TDR-{area_code}-00001, "
            f"got {certificate['serial_number']}"
        )
        assert certificate["units_face"] == CANONICAL_BASELINE_UNITS
        assert certificate["units_remaining"] == CANONICAL_BASELINE_UNITS
        assert certificate["holder_party_id"] == scenario["landowner"]["id"]
        assert certificate["generation"] == 1, "a root certificate is generation 1"
        assert certificate.get("parent_certificate_id") is None, "a root has no parent"
        assert certificate["lifecycle_status"] == "ISSUED"
        assert certificate["market_status"] == "HELD"
        assert certificate["origin_sending_area_id"] == scenario["area"]["id"]
        assert certificate["origin_neighborhood_code"] == "NB-EAST"
        assert_same_instant(certificate["issued_at"], CLOCK, "issued_at")

        # Every cascaded entity is already settled on the very next read.
        application = fetch_application(approved["id"])
        assert_severance_application(application)
        assert application["status"] == "CERTIFIED", (
            f"the application is already CERTIFIED, got {application['status']}"
        )
        assert application["certified_by_user_id"] == ADMIN_USER_ID, (
            "the certifying operator identity is recorded immediately"
        )
        assert application["version"] == approved["version"] + 1, (
            f"the certification increments the application version once, got {application['version']}"
        )

        easement = fetch_easement(certificate["conservation_easement_id"])
        assert_conservation_easement(easement)
        assert easement["recording_status"] == "RECORDED", (
            f"the easement is already on the register, got {easement['recording_status']}"
        )
        assert easement["recording_reference"] == f"EAS-{apn}-1", (
            f"the reference is minted from the parcel apn, got {easement['recording_reference']}"
        )
        assert_same_instant(easement["recorded_at"], CLOCK, "recorded_at")
        assert easement["compliance_status"] == "COMPLIANT", "stewardship opens clean"
        assert easement["amendment_count"] == 0, "a first certification amends nothing"
        assert easement["units_issued_total"] == CANONICAL_BASELINE_UNITS
        assert easement["units_outstanding"] == CANONICAL_BASELINE_UNITS
        assert easement["units_redeemed_confirmed"] == 0
        assert easement["units_retired"] == 0
        assert easement["restricted_acres"] == pytest.approx(100.00, abs=0.01), (
            f"severing the whole baseline encumbers all 100.00 acres, got {easement['restricted_acres']}"
        )
        assert easement["permitted_residual_units"] == 2, (
            f"2 existing dwellings plus 22 baseline less 22 severed leaves 2, "
            f"got {easement['permitted_residual_units']}"
        )

        parcel = fetch_parcel(scenario["parcel"]["id"])
        assert_sending_parcel(parcel)
        assert parcel["severed_units"] == CANONICAL_BASELINE_UNITS, (
            f"the parcel's severed count is already updated, got {parcel['severed_units']}"
        )
        assert parcel["remaining_units"] == 0, f"nothing remains, got {parcel['remaining_units']}"
        assert parcel["parcel_status"] == "FULLY_SEVERED", (
            f"an emptied parcel is FULLY_SEVERED, got {parcel['parcel_status']}"
        )
        assert parcel["easement_status"] == "RECORDED", (
            f"the parcel records its easement immediately, got {parcel['easement_status']}"
        )
        assert parcel["restricted_acres"] == pytest.approx(100.00, abs=0.01), (
            f"the parcel mirrors the easement acreage, got {parcel['restricted_acres']}"
        )

        area = fetch_sending_area(scenario["area"]["id"])
        assert_sending_area(area)
        assert area["severed_units_total"] == CANONICAL_BASELINE_UNITS, (
            f"the area's severed total is already recomputed, got {area['severed_units_total']}"
        )
        assert area["issued_certificate_count"] == 1, (
            f"the area has issued one certificate, got {area['issued_certificate_count']}"
        )
        assert area["status"] == "ACTIVE", (
            f"22 severed units is far below the 200-unit cap, got {area['status']}"
        )

        holder = fetch_party(scenario["landowner"]["id"])
        assert holder["units_held"] == CANONICAL_BASELINE_UNITS, (
            f"the applicant's holdings are already reconciled, got {holder['units_held']}"
        )
        assert holder["certificates_held_count"] == 1, (
            f"the applicant holds exactly one certificate, got {holder['certificates_held_count']}"
        )

        rows, meta = validate_paginated(
            api_client.list_certificate_transfers(
                ADMIN, params={"certificate_id": certificate["id"], "limit": 100, "offset": 0}
            )
        )
        assert meta["total_count"] == 1, (
            f"the chain of title opens with exactly one row, got {meta['total_count']}"
        )
        issuance = rows[0]
        assert_certificate_transfer(issuance)
        assert issuance["transfer_type"] == "ISSUANCE", (
            f"the opening row is an ISSUANCE, got {issuance['transfer_type']}"
        )
        assert issuance["seq_no"] == 1, f"the opening row is seq_no 1, got {issuance['seq_no']}"
        assert issuance.get("from_party_id") is None, "an issuance has no transferor"
        assert issuance["to_party_id"] == scenario["landowner"]["id"], "the applicant is the transferee"
        assert issuance["units"] == CANONICAL_BASELINE_UNITS
        assert issuance.get("price_cents") is None, "an issuance carries no price"
        assert issuance.get("market_transaction_id") is None, "an issuance has no market transaction"
        assert_same_instant(issuance["recorded_at"], CLOCK, "recorded_at")

        # The filtered listings see the settled state too.
        _, held_meta = validate_paginated(
            api_client.list_certificates(
                ADMIN,
                params={"holder_party_id": scenario["landowner"]["id"], "limit": 100, "offset": 0},
            )
        )
        assert held_meta["total_count"] == 1, (
            f"the holder filter already matches the new certificate, got {held_meta['total_count']}"
        )
        _, recorded_meta = validate_paginated(
            api_client.list_conservation_easements(
                ADMIN, params={"recording_status": "RECORDED", "limit": 100, "offset": 0}
            )
        )
        assert recorded_meta["total_count"] == 1, (
            f"the recording-status filter already matches, got {recorded_meta['total_count']}"
        )
        _, certified_meta = validate_paginated(
            api_client.list_severance_applications(
                ADMIN, params={"status": "CERTIFIED", "limit": 100, "offset": 0}
            )
        )
        assert certified_meta["total_count"] == 1, (
            f"the status filter already matches, got {certified_meta['total_count']}"
        )

    def test_a_second_certification_is_refused_and_changes_nothing_it_can_be_read_from(self):
        """The terminal application refuses a repeat certification, and every cascaded read is byte-for-byte where it was.

        PRD §3.5: "The application must be in `APPROVED`, otherwise `ERR_APPLICATION_NOT_APPROVED`."
        PRD §2.10: "14. The severance application is `APPROVED` before certification; otherwise `ERR_APPLICATION_NOT_APPROVED` (409)."
        PRD §2.7: "There is no deferred reconciliation and no eventual convergence — a read taken immediately after a write observes the fully settled state."
        PRD §3.5: "At most one easement ever exists per parcel."
        PRD §2.4: "`version` is an integer that starts at 1 when the row is created and increases by exactly one on every mutation of that row, including mutations reached through a cascade rather than through a direct request."

        Design: Corner/consistency_model/every_cascade_effect_is_readable_the_instant_the_response_returns
        """
        scenario = _approved_severance()
        approved_id = scenario["application"]["id"]
        certificate = validate_success(
            api_client.certify_severance_application(
                approved_id, make_admin_headers(ADMIN_USER_ID), {}
            ),
            201,
        )
        settled = {
            "application": fetch_application(approved_id),
            "easement": fetch_easement(certificate["conservation_easement_id"]),
            "parcel": fetch_parcel(scenario["parcel"]["id"]),
            "area": fetch_sending_area(scenario["area"]["id"]),
            "party": fetch_party(scenario["landowner"]["id"]),
            "certificate": fetch_certificate(certificate["id"]),
        }

        validate_error(
            api_client.certify_severance_application(
                approved_id, make_admin_headers(ADMIN_USER_ID), {}
            ),
            ApiErrorId.ERR_APPLICATION_NOT_APPROVED.value,
        )

        replayed = {
            "application": fetch_application(approved_id),
            "easement": fetch_easement(certificate["conservation_easement_id"]),
            "parcel": fetch_parcel(scenario["parcel"]["id"]),
            "area": fetch_sending_area(scenario["area"]["id"]),
            "party": fetch_party(scenario["landowner"]["id"]),
            "certificate": fetch_certificate(certificate["id"]),
        }
        for name, before in settled.items():
            assert replayed[name] == before, (
                f"the refused certification must leave the {name} exactly as it was: "
                f"{replayed[name]!r} != {before!r}"
            )

        _, easement_meta = validate_paginated(
            api_client.list_conservation_easements(
                ADMIN,
                params={"sending_parcel_id": scenario["parcel"]["id"], "limit": 100, "offset": 0},
            )
        )
        assert easement_meta["total_count"] == 1, (
            f"at most one easement ever exists per parcel, got {easement_meta['total_count']}"
        )
        _, certificate_meta = validate_paginated(
            api_client.list_certificates(
                ADMIN,
                params={"conservation_easement_id": certificate["conservation_easement_id"],
                        "limit": 100, "offset": 0},
            )
        )
        assert certificate_meta["total_count"] == 1, (
            f"the refused certification minted no second certificate, got {certificate_meta['total_count']}"
        )
