"""The three pinned versions, and the checkpoint that expires a document."""

from test_helpers import (
    ApiErrorId,
    assertions,
    constants,
    factories,
    fixtures,
    validate_error,
    validate_success,
)
from test_helpers.test_users import (
    COMPLIANCE_OFFICER,
    PLATFORM_ADMIN,
    make_guest_headers,
)


def test_booking_on_the_pre_activation_listing_version_is_refused_with_412(api):
    """Activation moved the listing to version 2; a request pinned at 1 is rejected.

    The stale value is the only thing wrong with the request — the identical body
    resubmitted against the live version is accepted — and nothing is written on the
    way out, so the listing keeps no reservation from the refused attempt.

    PRD: "When `expected_property_version` does not equal the listing's current `version`, the booking is refused with `ERR_PROPERTY_VERSION_STALE` (HTTP 412)."
    PRD: "In all three cases the version field is a required input, not an optional one, and a mismatch against the stored parent `version` is rejected with HTTP 412 before any state is written."
    PRD: "Note that a second booking of an unchanged listing is entirely legitimate product behaviour, so this rule cannot be reduced to a state precondition — only the version comparison expresses it."

    Design: Corner/cross-cutting complexity layers/stale_property_version_on_reservation_create_returns_412
    """
    cast = fixtures.setup_waiver_listing(
        api,
        activate=False,
        guest_name="Stale Property Guest",
        guest_email="staleprop@guest.test",
    )
    stale_version = cast.property["version"]
    activated = validate_success(
        api.activate_property(cast.property_id, cast.host_headers)
    )
    current_version = activated["version"]
    assert (stale_version, current_version) == (1, 2), (
        "the DRAFT listing stands at version 1 and activation moves it to 2, "
        "got {0} then {1}".format(stale_version, current_version)
    )

    payload = factories.reservation_payload(
        cast.guest_id, cast.property_id, stale_version
    )
    validate_error(
        api.create_reservation(cast.guest_headers, **payload),
        ApiErrorId.ERR_PROPERTY_VERSION_STALE,
        expected_status=412,
    )
    assertions.assert_page(
        api.list_reservations(cast.host_headers, property_id=cast.property_id),
        total_count=0,
    )
    assertions.assert_fields(
        fixtures.read_property(api, cast), "property", version=2
    )

    payload["expected_property_version"] = current_version
    accepted = validate_success(
        api.create_reservation(cast.guest_headers, **payload), expected_status=201
    )
    assertions.assert_fields(
        accepted,
        "reservation",
        stay_state="REQUESTED",
        property_id=cast.property_id,
        guest_id=cast.guest_id,
    )


def test_filing_against_a_stale_stay_snapshot_answers_before_the_state_gate(api):
    """A 412 on the pinned version, not a 409 on the stay that is only CONFIRMED.

    The stay has not been completed, so the claim is doomed twice over; the version
    comparison of §2.7 runs first and is the reported failure. Nothing is written:
    the stay keeps its version, its deposit stays HELD, and no claim row exists.

    PRD: "When `expected_reservation_version` does not equal the reservation's current `version`, the claim is refused with `ERR_RESERVATION_VERSION_STALE` (HTTP 412), because the deposit may already have been released or applied by another claim in the interim."
    PRD: "In all three cases the version field is a required input, not an optional one, and a mismatch against the stored parent `version` is rejected with HTTP 412 before any state is written."
    PRD: "Filing a second claim against the same completed stay is permitted, so again no state precondition can substitute for the version check."

    Design: Corner/cross-cutting complexity layers/stale_reservation_version_on_claim_create_returns_412
    """
    cast = fixtures.setup_deposit_listing(
        api, guest_name="Stale Stay Guest", guest_email="stalestay@guest.test"
    )
    reservation = fixtures.book_stay(api, cast, check_out="2026-08-12")
    stale_version = reservation["version"]
    confirmed = fixtures.confirm_stay(api, cast, reservation["id"])
    assert (stale_version, confirmed["version"]) == (1, 2), (
        "creation leaves the stay at version 1 and confirmation moves it to 2, "
        "got {0} then {1}".format(stale_version, confirmed["version"])
    )
    assertions.assert_fields(
        confirmed, "reservation", stay_state="CONFIRMED", deposit_state="HELD"
    )

    refusal = validate_error(
        api.create_damage_claim(
            cast.host_headers,
            **factories.damage_claim_payload(reservation["id"], 60000, stale_version)
        ),
        ApiErrorId.ERR_RESERVATION_VERSION_STALE,
        expected_status=412,
    )
    assert refusal["error_id"] != "ERR_STAY_NOT_COMPLETED", (
        "the pinned-version check outranks the stay-state precondition"
    )
    assertions.assert_page(
        api.list_damage_claims(cast.host_headers, reservation_id=reservation["id"]),
        total_count=0,
    )
    assertions.assert_fields(
        validate_success(api.get_reservation(reservation["id"], cast.host_headers)),
        "reservation",
        version=2,
        deposit_state="HELD",
        deposit_hold_cents=50000,
    )


def test_a_rescored_guest_defeats_a_ban_pinned_at_the_old_version(api):
    """The payment signal moved the guest to version 2, so the ban is a 412.

    The reason code on that ban is unevidenced as well — this guest has no
    substantiated incident — but the grounds check never runs, because the version
    comparison of §2.7 fires ahead of it and refuses before any state is written.

    PRD: "When `expected_guest_version` does not equal the guest's current `version`, the entry is refused with `ERR_GUEST_VERSION_STALE` (HTTP 412), because a claim overturned on appeal or a document expiry may have moved the grounds out from under it."
    PRD: "The creation is also guarded by optimistic concurrency on the guest: the submitted `expected_guest_version` must equal the guest's stored `version`, and a stale value is refused with `ERR_GUEST_VERSION_STALE` as described in §2.7."
    PRD: "`SUBSTANTIATED_INCIDENT` requires the guest's `substantiated_incident_count` to be at least 1."
    PRD: "Recording a signal re-runs the risk score, which may re-band `risk_tier` and, if the re-band reaches the critical band, fire the automatic platform ban described in §3.9."

    Design: Corner/cross-cutting complexity layers/stale_guest_version_on_blocklist_create_returns_412
    """
    cast = fixtures.setup_waiver_listing(
        api, guest_name="Stale Guest Version", guest_email="staleguest@guest.test"
    )
    stale_version = cast.guest["version"]
    rescored = validate_success(
        api.record_payment_signal(
            cast.guest_id,
            PLATFORM_ADMIN,
            payment_risk_signal="ADVERSE",
            chargeback_count=1,
        )
    )
    assert (stale_version, rescored["version"]) == (1, 2), (
        "the guest stands at version 1 and the signal moves it to 2, "
        "got {0} then {1}".format(stale_version, rescored["version"])
    )
    assertions.assert_guest_risk(rescored, 70, "HIGH")
    assertions.assert_fields(
        rescored, "guest", substantiated_incident_count=0
    )

    refusal = validate_error(
        api.create_blocklist_entry(
            cast.host_headers,
            **factories.blocklist_entry_payload(
                cast.guest_id,
                "PROPERTY",
                "SUBSTANTIATED_INCIDENT",
                stale_version,
                property_id=cast.property_id,
            )
        ),
        ApiErrorId.ERR_GUEST_VERSION_STALE,
        expected_status=412,
    )
    assert refusal["error_id"] != "ERR_BLOCKLIST_GROUNDS_NOT_MET", (
        "the pinned-version check runs before the grounds check"
    )
    assertions.assert_page(
        api.list_blocklist_entries(COMPLIANCE_OFFICER, guest_id=cast.guest_id),
        total_count=0,
    )
    assertions.assert_fields(
        fixtures.read_guest(api, cast),
        "guest",
        active_blocklist_scope_count=0,
        version=2,
    )


def test_only_the_sweep_expires_a_document_and_it_rebands_the_guest_with_it(api):
    """Nothing moves while the clock sits before expiry; one run does all of it.

    The government ID lapses on 2026-08-20 and the selfie not until 2030, so the
    verified position survives until the clock passes the earlier date and the
    checkpoint is run. That single run expires exactly one document, drops the guest
    below the government-ID threshold and withdraws the 15-point verified credit.

    PRD: "Every identity document whose `review_state` is `PENDING` or `ACCEPTED` and whose `expires_on` is strictly earlier than the captured reading moves to `review_state` `EXPIRED`."
    PRD: "Each such move re-runs the affected guest's verification recomputation of §3.2, which may drop `accepted_doc_count` and `accepted_gov_id_count` below their thresholds and pull `verification_state` back out of `VERIFIED`, which in turn re-runs the risk score."
    PRD: "Otherwise, if the guest holds any document in `EXPIRED`, the state is `VERIFICATION_EXPIRED`."
    PRD: "The sweep responds with a report of what each phase moved: `swept_at` carries the captured clock reading, `documents_expired` counts the Phase 1 moves, `incidents_sla_breached` counts the Phase 2 flags, `claims_denied_sla` counts the Phase 3 denials, `claims_settled` counts the Phase 4 moves into `SETTLED`, `claims_closed_denied` counts the Phase 4 moves into `CLOSED_DENIED`, `deposits_released` counts the Phase 5 releases, and `dispute_windows_expired` counts the Phase 6 expiries."

    Design: Corner/cross-cutting complexity layers/adjudication_sweep_expires_accepted_document_and_rebands_risk
    """
    fixtures.set_clock(api, constants.PROCESS_START_UTC)
    guest = fixtures.create_guest(
        api, full_name="Expiring Doc Guest", email="expiring@guest.test"
    )
    guest_headers = make_guest_headers(guest["id"])
    government_id = validate_success(
        api.create_identity_document(
            guest_headers,
            **factories.government_id_payload(
                guest["id"],
                document_ref="blob/gov-exp",
                expires_on="2026-08-20T00:00:00Z",
            )
        ),
        expected_status=201,
    )
    validate_success(
        api.review_identity_document(
            government_id["id"], COMPLIANCE_OFFICER, decision="ACCEPT"
        )
    )
    selfie = validate_success(
        api.create_identity_document(
            guest_headers,
            **factories.selfie_payload(
                guest["id"],
                document_ref="blob/selfie-long",
                expires_on="2030-01-01T00:00:00Z",
            )
        ),
        expected_status=201,
    )
    accepted_selfie = validate_success(
        api.review_identity_document(
            selfie["id"], COMPLIANCE_OFFICER, decision="ACCEPT"
        )
    )
    assertions.assert_fields(accepted_selfie, "identity_document", review_state="ACCEPTED")
    before = validate_success(api.get_guest_risk_profile(guest["id"], COMPLIANCE_OFFICER))
    assertions.assert_fields(
        before,
        "risk_profile",
        verification_state="VERIFIED",
        risk_score=20,
        risk_tier="LOW",
    )

    fixtures.set_clock(api, constants.DOC_EXPIRY_SWEEP_CLOCK_UTC)
    report = fixtures.run_sweep(api)
    assert report["swept_at"].startswith("2026-09-01T00:00:00"), (
        "the report carries the captured clock reading, got {0}".format(
            report["swept_at"]
        )
    )
    assertions.assert_fields(
        report,
        "sweep_report",
        documents_expired=1,
        incidents_sla_breached=0,
        claims_denied_sla=0,
        claims_settled=0,
        claims_closed_denied=0,
        deposits_released=0,
        dispute_windows_expired=0,
    )

    assertions.assert_fields(
        validate_success(api.get_identity_document(government_id["id"], guest_headers)),
        "identity_document",
        review_state="EXPIRED",
    )
    assertions.assert_fields(
        validate_success(api.get_identity_document(selfie["id"], guest_headers)),
        "identity_document",
        review_state="ACCEPTED",
    )
    rebanded = validate_success(api.get_guest(guest["id"], PLATFORM_ADMIN))
    assertions.assert_fields(
        rebanded,
        "guest",
        accepted_doc_count=1,
        accepted_gov_id_count=0,
        verification_state="VERIFICATION_EXPIRED",
    )
    assertions.assert_guest_risk(rebanded, 35, "ELEVATED")
