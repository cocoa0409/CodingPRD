"""Endpoint behaviour: CRUD surfaces, action side effects, cross-reference links and pure reads."""

from test_helpers import (
    NON_EXISTENT_UUID,
    PROGRAM_ADMIN,
    ApiErrorId,
    assert_device,
    assert_device_counters,
    assert_instant,
    assert_instant_null,
    assert_ledger_tuple,
    assert_service_transfer,
    factories as f,
    fixtures as fx,
    validate_error,
    validate_paginated,
    validate_success,
)

CLOCK = "2026-08-01T00:00:00Z"
JUNE_START = "2026-06-01T00:00:00Z"
JULY_FILING = "2026-07-02T00:00:00Z"
IDLE_30_INSTANT = "2026-08-31T00:00:00Z"
CURE_DEADLINE = "2026-09-15T23:59:59.999Z"
PORT_FREEZE_UNTIL = "2026-09-30T00:00:00Z"
ONE_MS_BEFORE_FREEZE_LIFTS = "2026-09-29T23:59:59.999Z"
AFTER_FREEZE = "2026-10-01T00:00:00Z"

BASIC_IMEI = "350000000000041"
SMART_IMEI = "350000000000082"
RIVAL_IMEI = "350000000000123"


def test_the_handset_catalogue_reads_and_filters_without_leaking_a_rivals_stock(api):
    """Create, single read and a composed multi-filter list over two carriers' catalogues.

    PRD: "A carrier can be read individually, complete with its live ledger and device
    counters; handsets can be read individually or listed with filters on `provider_id`, on
    `issued_enrollment_id`, on `status` and on `model_tier`."

    Design: Corner/endpoints/device_create_read_and_filtered_list_round_trip
    """
    fx.set_clock(api, CLOCK)
    first_carrier, rival_carrier = fx.register_provider_pair(api)

    cheap = validate_success(
        api.stock_device(
            first_carrier["id"],
            f.device_payload(imei=BASIC_IMEI, model_tier="BASIC", unit_cost_cents=2100),
            fx.provider_headers(first_carrier),
        ),
        201,
    )
    premium = validate_success(
        api.stock_device(
            first_carrier["id"],
            f.device_payload(imei=SMART_IMEI, model_tier="SMART", unit_cost_cents=5900),
            fx.provider_headers(first_carrier),
        ),
        201,
    )
    rival = validate_success(
        api.stock_device(
            rival_carrier["id"],
            f.device_payload(imei=RIVAL_IMEI, model_tier="SMART", unit_cost_cents=6100),
            fx.provider_headers(rival_carrier),
        ),
        201,
    )
    for handset in (cheap, premium, rival):
        assert_device(handset)
        assert handset["status"] == "IN_STOCK"
        assert handset["issued_enrollment_id"] is None
        assert_instant_null(handset["issued_at"], "issued_at")

    read_back = validate_success(api.get_device(premium["id"], PROGRAM_ADMIN))
    assert read_back["imei"] == SMART_IMEI
    assert read_back["model_tier"] == "SMART"
    assert read_back["unit_cost_cents"] == 5900
    assert read_back["provider_id"] == first_carrier["id"]

    first_page, first_meta = validate_paginated(
        api.list_devices(
            PROGRAM_ADMIN, {"provider_id": first_carrier["id"], "limit": 1, "offset": 0}
        )
    )
    assert first_meta["limit"] == 1
    assert first_meta["offset"] == 0
    assert first_meta["total_count"] == 2, (
        f"the total counts the filtered set, not the catalogue, got {first_meta['total_count']}"
    )
    assert first_meta["has_more"] is True

    second_page, second_meta = validate_paginated(
        api.list_devices(
            PROGRAM_ADMIN, {"provider_id": first_carrier["id"], "limit": 1, "offset": 1}
        )
    )
    assert second_meta["limit"] == 1
    assert second_meta["offset"] == 1
    assert second_meta["total_count"] == 2
    assert second_meta["has_more"] is False

    paged = [first_page[0]["id"], second_page[0]["id"]]
    assert len(set(paged)) == 2, "the two pages name two different handsets"
    assert sorted(paged) == sorted([cheap["id"], premium["id"]]), (
        "the carrier filter covers exactly its own two handsets"
    )
    assert rival["id"] not in paged, "a rival's handset never appears under the carrier filter"

    composed, composed_meta = validate_paginated(
        api.list_devices(
            PROGRAM_ADMIN, {"provider_id": first_carrier["id"], "model_tier": "SMART"}
        )
    )
    assert composed_meta["total_count"] == 1, (
        f"provider_id and model_tier compose, got {composed_meta['total_count']}"
    )
    assert composed[0]["id"] == premium["id"]

    _all_rows, all_meta = validate_paginated(
        api.list_devices(PROGRAM_ADMIN, {"status": "IN_STOCK"})
    )
    assert all_meta["total_count"] == 3, (
        f"the unfiltered status query spans both carriers, got {all_meta['total_count']}"
    )

    assert fx.refresh_provider(api, first_carrier["id"])["devices_total_count"] == 2
    assert fx.refresh_provider(api, rival_carrier["id"])["devices_total_count"] == 1


def test_activity_cures_the_flag_never_rewinds_the_anchor_and_needs_a_live_benefit(api):
    """The three declared side effects of the usage action, isolated one at a time.

    PRD: "The activity anchor only ever moves forward: an event carrying an explicit
    `usage_at` earlier than the anchor already recorded is still accepted, but the anchor is
    not rewound."

    Design: Corner/endpoints/usage_endpoint_cures_the_flag_never_rewinds_and_needs_an_active_benefit
    """
    fx.set_clock(api, CLOCK)
    provider = fx.register_provider(api)
    agent = fx.provider_headers(provider)
    address = fx.register_distinct_address(api, 1)
    applicant = fx.eligible_applicant(api, address["id"])
    benefit = fx.enroll(
        api,
        provider,
        applicant["subscriber"],
        applicant["check"],
        address,
        service_type="VOICE",
        benefit_start_date=CLOCK,
    )
    assert benefit["usage_status"] == "PENDING_FIRST_USE"
    assert_instant_null(benefit["last_usage_at"], "last_usage_at")
    assert benefit["audit_risk_score"] == 0

    fx.set_clock(api, IDLE_30_INSTANT)
    swept = fx.sweep(api, provider["id"])
    assert_instant(swept["swept_at"], IDLE_30_INSTANT, "swept_at")
    assert swept["non_usage_flagged_enrollment_ids"] == [benefit["id"]]

    flagged = fx.refresh_enrollment(api, benefit["id"])
    assert flagged["usage_status"] == "NON_USAGE_FLAGGED"
    assert_instant(flagged["non_usage_flagged_at"], IDLE_30_INSTANT, "non_usage_flagged_at")
    assert_instant(flagged["cure_deadline_at"], CURE_DEADLINE, "cure_deadline_at")
    assert flagged["audit_risk_score"] == 30, (
        f"the non-usage flag carries a weight of 30, got {flagged['audit_risk_score']}"
    )

    fx.set_clock(api, CURE_DEADLINE)
    cured = validate_success(api.record_usage(benefit["id"], f.usage_payload(), agent))
    assert cured["usage_status"] == "USING"
    assert_instant(cured["last_usage_at"], CURE_DEADLINE, "last_usage_at")
    assert_instant_null(cured["non_usage_flagged_at"], "non_usage_flagged_at")
    assert_instant_null(cured["cure_deadline_at"], "cure_deadline_at")
    assert cured["audit_risk_score"] == 0, (
        f"clearing the flag returns the risk score to 0, got {cured['audit_risk_score']}"
    )

    backdated = validate_success(
        api.record_usage(
            benefit["id"],
            f.usage_payload(usage_at="2026-09-01T00:00:00Z", usage_kind="DATA_SESSION"),
            agent,
        )
    )
    assert backdated["usage_status"] == "USING", "further activity on USING is a self-edge"
    assert_instant(backdated["last_usage_at"], CURE_DEADLINE, "last_usage_at")

    stopped = fx.de_enroll(api, benefit["id"], reason="SUBSCRIBER_REQUEST", headers=agent)
    assert stopped["benefit_status"] == "DE_ENROLLED"

    refused = api.record_usage(benefit["id"], f.usage_payload(), agent)
    validate_error(refused, ApiErrorId.ENROLLMENT_NOT_ACTIVE.value, 409)
    assert_instant(
        fx.refresh_enrollment(api, benefit["id"])["last_usage_at"],
        CURE_DEADLINE,
        "last_usage_at",
    )


def _one_benefit_ready_to_port(api):
    """A holding carrier, a gaining carrier and one ACTIVE VOICE benefit started 2026-08-01."""
    fx.set_clock(api, CLOCK)
    holding, gaining = fx.register_provider_pair(api, licensed_state_codes=["TX"])
    address = fx.register_distinct_address(api, 1)
    applicant = fx.eligible_applicant(api, address["id"])
    benefit = fx.enroll(
        api,
        holding,
        applicant["subscriber"],
        applicant["check"],
        address,
        service_type="VOICE",
        benefit_start_date=CLOCK,
    )
    assert_instant(benefit["port_freeze_until"], PORT_FREEZE_UNTIL, "port_freeze_until")
    return {"holding": holding, "gaining": gaining, "benefit": benefit}


def test_the_port_link_forms_only_when_both_foreign_keys_resolve(api):
    """Two unresolvable links leave no row and no version bump; the third supersedes on repeat.

    PRD: "The system snapshots `source_provider_id` from the benefit's current carrier, stamps
    `requested_at` with the current instant, and records in `port_freeze_until_snapshot` the
    exact freeze anchor it tested, so an audit can later show which anchor the port cleared."

    Design: Corner/endpoints/transfer_link_requires_both_the_enrollment_and_the_gaining_carrier
    """
    context = _one_benefit_ready_to_port(api)
    holding = context["holding"]
    gaining = context["gaining"]
    benefit_id = context["benefit"]["id"]
    agent = fx.provider_headers(holding)

    fx.set_clock(api, AFTER_FREEZE)
    first_version = fx.enrollment_version(api, benefit_id)

    unknown_benefit = api.create_service_transfer(
        f.service_transfer_payload(
            enrollment_id=NON_EXISTENT_UUID,
            target_provider_id=gaining["id"],
            expected_enrollment_version=first_version,
            subscriber_consent_ref="CONSENT-31",
        ),
        agent,
    )
    validate_error(unknown_benefit, ApiErrorId.ENROLLMENT_NOT_FOUND.value, 404)

    unknown_carrier = api.create_service_transfer(
        f.service_transfer_payload(
            enrollment_id=benefit_id,
            target_provider_id=NON_EXISTENT_UUID,
            expected_enrollment_version=first_version,
            subscriber_consent_ref="CONSENT-31",
        ),
        agent,
    )
    validate_error(unknown_carrier, ApiErrorId.PROVIDER_NOT_FOUND.value, 404)

    _empty, empty_meta = validate_paginated(
        api.list_service_transfers(PROGRAM_ADMIN, {"enrollment_id": benefit_id})
    )
    assert empty_meta["total_count"] == 0, "neither refused link created a row"
    assert fx.enrollment_version(api, benefit_id) == first_version, (
        "a refused link never advances the benefit's version"
    )

    opened = validate_success(
        api.create_service_transfer(
            f.service_transfer_payload(
                enrollment_id=benefit_id,
                target_provider_id=gaining["id"],
                expected_enrollment_version=first_version,
                subscriber_consent_ref="CONSENT-31",
            ),
            agent,
        ),
        201,
    )
    assert_service_transfer(opened)
    assert opened["status"] == "REQUESTED"
    assert opened["source_provider_id"] == holding["id"], (
        "the losing carrier is derived from the benefit, never taken from the request body"
    )
    assert_instant(
        opened["port_freeze_until_snapshot"], PORT_FREEZE_UNTIL, "port_freeze_until_snapshot"
    )
    assert_instant(opened["requested_at"], AFTER_FREEZE, "requested_at")

    second_version = fx.enrollment_version(api, benefit_id)
    assert second_version == first_version + 1, (
        f"creating the request advances the benefit's version, got {second_version}"
    )

    superseding = validate_success(
        api.create_service_transfer(
            f.service_transfer_payload(
                enrollment_id=benefit_id,
                target_provider_id=gaining["id"],
                expected_enrollment_version=second_version,
                subscriber_consent_ref="CONSENT-32",
            ),
            agent,
        ),
        201,
    )
    assert superseding["status"] == "REQUESTED"
    assert superseding["subscriber_consent_ref"] == "CONSENT-32"

    displaced = fx.refresh_transfer(api, opened["id"])
    assert displaced["status"] == "SUPERSEDED", (
        f"the older in-flight request stands down, got {displaced['status']}"
    )
    assert_instant(displaced["completed_at"], AFTER_FREEZE, "completed_at")

    assert fx.refresh_enrollment(api, benefit_id)["provider_id"] == holding["id"], (
        "a request alone never moves the benefit"
    )
    _rows, both_meta = validate_paginated(
        api.list_service_transfers(PROGRAM_ADMIN, {"enrollment_id": benefit_id})
    )
    assert both_meta["total_count"] == 2


def test_reading_the_carrier_ledger_twice_returns_the_same_row_at_the_same_version(api):
    """Every derived carrier field reconciles against its mutations, and a read changes nothing.

    PRD: "`version` (integer): starts at 1 when the row is created and increases by exactly
    one on every subsequent mutation."

    Design: Corner/endpoints/provider_ledger_read_is_pure_and_reflects_every_prior_mutation
    """
    fx.set_clock(api, JUNE_START)
    provider = fx.register_provider(api, licensed_state_codes=["TX"])
    handsets = fx.stock_devices(api, provider, [("BASIC", 2100), ("BASIC", 2200)])
    benefits = []
    for index in (1, 2):
        address = fx.register_distinct_address(api, index)
        applicant = fx.eligible_applicant(api, address["id"])
        benefits.append(
            fx.enroll(
                api,
                provider,
                applicant["subscriber"],
                applicant["check"],
                address,
                service_type="VOICE",
                benefit_start_date=JUNE_START,
            )
        )
    fx.issue_device(api, benefits[0]["id"], provider, device_id=handsets[0]["id"])

    fx.set_clock(api, JULY_FILING)
    claim = fx.file_claim(api, fx.draft_claim(api, provider, "2026-06")["id"], provider)
    assert claim["final_amount_cents"] == 1850, (
        f"two full-month voice lines at 925 each, got {claim['final_amount_cents']}"
    )

    first_read = validate_success(api.get_provider(provider["id"], PROGRAM_ADMIN))
    assert first_read["active_enrollment_count"] == 2
    assert first_read["open_claim_count"] == 1
    assert_ledger_tuple(first_read, 1850, 0, 1850, False)
    assert_device_counters(first_read, 2, 1, 1, 0, 0)

    second_read = validate_success(api.get_provider(provider["id"], PROGRAM_ADMIN))
    assert second_read["version"] == first_read["version"], (
        f"a read is not a mutation, so the version holds at {first_read['version']}, "
        f"got {second_read['version']}"
    )
    for field in (
        "active_enrollment_count",
        "claim_gross_cents",
        "recouped_cents",
        "net_reimbursed_cents",
        "open_claim_count",
        "devices_total_count",
        "devices_in_stock_count",
        "devices_issued_count",
        "devices_reclaim_pending_count",
    ):
        assert second_read[field] == first_read[field], (
            f"{field} moved between two identical reads: "
            f"{first_read[field]} then {second_read[field]}"
        )

    _filed, filed_meta = validate_paginated(
        api.list_claims(PROGRAM_ADMIN, {"provider_id": provider["id"], "status": "FILED"})
    )
    assert filed_meta["total_count"] == 1

    issued, issued_meta = validate_paginated(
        api.list_devices(
            PROGRAM_ADMIN,
            {"provider_id": provider["id"], "issued_enrollment_id": benefits[0]["id"]},
        )
    )
    assert issued_meta["total_count"] == 1
    assert issued[0]["id"] == handsets[0]["id"]


def test_the_port_needs_the_freeze_lifted_a_different_carrier_and_a_live_request(api):
    """Each of the three admission conditions is isolated by one single-variable change.

    PRD: "That window is half-open — a request at exactly `port_freeze_until` is accepted."

    Design: Corner/endpoints/transfer_is_gated_on_the_freeze_the_target_and_the_status
    """
    context = _one_benefit_ready_to_port(api)
    holding = context["holding"]
    gaining = context["gaining"]
    benefit_id = context["benefit"]["id"]
    agent = fx.provider_headers(holding)

    fx.set_clock(api, ONE_MS_BEFORE_FREEZE_LIFTS)
    version = fx.enrollment_version(api, benefit_id)
    too_early = api.create_service_transfer(
        f.service_transfer_payload(
            enrollment_id=benefit_id,
            target_provider_id=gaining["id"],
            expected_enrollment_version=version,
            subscriber_consent_ref="CONSENT-41",
        ),
        agent,
    )
    validate_error(too_early, ApiErrorId.PORT_FREEZE_ACTIVE.value, 409)
    assert fx.enrollment_version(api, benefit_id) == version, (
        "the refused request inside the freeze window left the benefit untouched"
    )

    fx.set_clock(api, PORT_FREEZE_UNTIL)
    nowhere_to_go = api.create_service_transfer(
        f.service_transfer_payload(
            enrollment_id=benefit_id,
            target_provider_id=holding["id"],
            expected_enrollment_version=version,
            subscriber_consent_ref="CONSENT-42",
        ),
        agent,
    )
    validate_error(nowhere_to_go, ApiErrorId.TRANSFER_SAME_PROVIDER.value, 422)

    opened = validate_success(
        api.create_service_transfer(
            f.service_transfer_payload(
                enrollment_id=benefit_id,
                target_provider_id=gaining["id"],
                expected_enrollment_version=version,
                subscriber_consent_ref="CONSENT-43",
            ),
            agent,
        ),
        201,
    )
    assert opened["status"] == "REQUESTED", (
        "one millisecond later the half-open window admits the very same request"
    )

    declined = validate_success(
        api.reject_service_transfer(
            opened["id"],
            f.transfer_reject_payload(
                rejection_reason="CONSENT_INVALID",
                rejection_note="consent reference could not be validated",
            ),
            fx.provider_headers(gaining),
        )
    )
    assert declined["status"] == "REJECTED"
    assert declined["rejection_reason"] == "CONSENT_INVALID"
    assert_instant(declined["completed_at"], PORT_FREEZE_UNTIL, "completed_at")

    untouched = fx.refresh_enrollment(api, benefit_id)
    assert untouched["provider_id"] == holding["id"]
    assert untouched["transfer_count"] == 0, (
        f"the rejection arm never ports the benefit, got {untouched['transfer_count']}"
    )

    reversal = api.accept_service_transfer(
        opened["id"], f.transfer_accept_payload(acceptance_note="second thoughts"),
        fx.provider_headers(gaining),
    )
    validate_error(reversal, ApiErrorId.TRANSFER_NOT_REQUESTED.value, 409)
    assert fx.refresh_transfer(api, opened["id"])["status"] == "REJECTED", (
        "REJECTED is terminal, so the refused acceptance changed nothing"
    )
    assert fx.refresh_provider(api, gaining["id"])["active_enrollment_count"] == 0
