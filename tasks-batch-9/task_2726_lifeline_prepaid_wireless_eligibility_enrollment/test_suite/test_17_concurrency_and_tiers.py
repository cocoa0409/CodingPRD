"""Cross-cutting layers: optimistic version pins, penalty-rate boundaries and immediate consistency."""

from test_helpers import (
    PROGRAM_ADMIN,
    ApiErrorId,
    assert_device,
    assert_household_address,
    assert_instant,
    assert_ledger_tuple,
    expected_recoupment,
    expected_risk_score,
    factories as f,
    fixtures as fx,
    validate_error,
    validate_paginated,
    validate_success,
)

CLOCK = "2026-08-01T00:00:00Z"
MAY_START = "2026-05-01T00:00:00Z"
FREEZE_LIFTED = "2026-06-30T00:00:00Z"
JUNE_START = "2026-06-01T00:00:00Z"
JUNE_16 = "2026-06-16T00:00:00Z"
JUNE_21 = "2026-06-21T00:00:00Z"
JULY_FILING = "2026-07-02T00:00:00Z"
COHORT_HASH = "1200NMAINST|APT4B|ELPASO|TX|79901"


def test_a_stale_benefit_version_refuses_the_port_and_never_bumps_the_benefit(api):
    """The pin is a genuine race guard: an intervening usage write invalidates the version the
    porting agent read, and the refusal itself leaves the benefit exactly where it was.

    PRD: "Opening a port request requires `expected_enrollment_version` carrying the client's
    last observed `version` of the target `Enrollment`. If it does not equal the enrollment's
    current `version`, the request is rejected with `ERR_STALE_ENROLLMENT_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/stale_enrollment_version_blocks_the_port_request
    """
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
        benefit_start_date=MAY_START,
    )
    assert_instant(benefit["port_freeze_until"], FREEZE_LIFTED, "port_freeze_until")

    stale_version = fx.enrollment_version(api, benefit["id"])
    used = fx.record_usage(api, benefit["id"], headers=fx.provider_headers(holding))
    assert used["usage_status"] == "USING"
    assert_instant(used["last_usage_at"], CLOCK, "last_usage_at")
    version_after_usage = used["version"]
    assert version_after_usage == stale_version + 1, (
        f"the usage write advanced the benefit by exactly one, got {version_after_usage} "
        f"from {stale_version}"
    )

    refused = api.create_service_transfer(
        f.service_transfer_payload(
            enrollment_id=benefit["id"],
            target_provider_id=gaining["id"],
            expected_enrollment_version=stale_version,
            subscriber_consent_ref="CONSENT-61",
        ),
        fx.provider_headers(holding),
    )
    validate_error(refused, ApiErrorId.STALE_ENROLLMENT_VERSION.value, 412)

    _rows, empty_meta = validate_paginated(
        api.list_service_transfers(PROGRAM_ADMIN, {"enrollment_id": benefit["id"]})
    )
    assert empty_meta["total_count"] == 0, "the refused port wrote no request row"

    fresh_version = fx.enrollment_version(api, benefit["id"])
    assert fresh_version == version_after_usage, (
        f"a refused write is not a mutation, so the benefit holds at {version_after_usage}, "
        f"got {fresh_version}"
    )

    opened = validate_success(
        api.create_service_transfer(
            f.service_transfer_payload(
                enrollment_id=benefit["id"],
                target_provider_id=gaining["id"],
                expected_enrollment_version=fresh_version,
                subscriber_consent_ref="CONSENT-61",
            ),
            fx.provider_headers(holding),
        ),
        201,
    )
    assert opened["status"] == "REQUESTED", (
        "the identical request carrying the fresh version is admitted"
    )
    assert opened["source_provider_id"] == holding["id"]

    final_version = fx.enrollment_version(api, benefit["id"])
    assert final_version == fresh_version + 1, (
        f"creating the request advances the benefit by one, got {final_version}"
    )

    settled = fx.refresh_enrollment(api, benefit["id"])
    assert settled["provider_id"] == holding["id"], (
        "an open request never moves the benefit between carriers"
    )
    assert_instant(settled["last_usage_at"], CLOCK, "last_usage_at")


def test_a_stale_carrier_version_refuses_the_draft_and_never_bumps_the_ledger(api):
    """Stocking one handset between the read and the draft is enough to invalidate the pin, and
    the refused draft leaves both the carrier version and its open-claim counter alone.

    PRD: "Opening a draft reimbursement claim requires `expected_provider_version` carrying the
    client's last observed `version` of the named `Provider`. A mismatch with the carrier's
    current `version` is rejected with `ERR_STALE_PROVIDER_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/stale_provider_version_blocks_the_claim_draft
    """
    fx.set_clock(api, JULY_FILING)
    provider = fx.register_provider(api, licensed_state_codes=["TX"])
    agent = fx.provider_headers(provider)
    address = fx.register_distinct_address(api, 1)
    applicant = fx.eligible_applicant(api, address["id"])
    fx.enroll(
        api,
        provider,
        applicant["subscriber"],
        applicant["check"],
        address,
        service_type="VOICE",
        benefit_start_date=JUNE_START,
    )

    before = fx.refresh_provider(api, provider["id"])
    assert before["open_claim_count"] == 0
    stale_version = before["version"]

    handset = fx.stock_device(api, provider, model_tier="BASIC", unit_cost_cents=2100)
    assert handset["status"] == "IN_STOCK"

    refused = api.create_claim(
        f.claim_payload(
            provider_id=provider["id"],
            service_month="2026-06",
            expected_provider_version=stale_version,
        ),
        agent,
    )
    validate_error(refused, ApiErrorId.STALE_PROVIDER_VERSION.value, 412)

    _rows, empty_meta = validate_paginated(
        api.list_claims(PROGRAM_ADMIN, {"provider_id": provider["id"]})
    )
    assert empty_meta["total_count"] == 0, "the refused draft wrote no claim row"

    after_refusal = fx.refresh_provider(api, provider["id"])
    fresh_version = after_refusal["version"]
    assert fresh_version == stale_version + 1, (
        f"the handset write bumped the carrier once, got {fresh_version} from {stale_version}"
    )
    assert after_refusal["open_claim_count"] == 0, (
        "the refused draft left the open-claim counter untouched"
    )

    draft = validate_success(
        api.create_claim(
            f.claim_payload(
                provider_id=provider["id"],
                service_month="2026-06",
                expected_provider_version=fresh_version,
            ),
            agent,
        ),
        201,
    )
    assert draft["status"] == "DRAFT"
    assert draft["provisional_amount_cents"] == 925, (
        f"one full-month voice line in a thirty-day month, got {draft['provisional_amount_cents']}"
    )
    assert draft["covered_enrollment_count"] == 1
    assert draft["final_amount_cents"] == 0, (
        f"a draft initialises the settled amount to 0, got {draft['final_amount_cents']}"
    )

    settled = fx.refresh_provider(api, provider["id"])
    assert settled["version"] == fresh_version + 1, (
        f"the admitted draft advances the carrier by one, got {settled['version']}"
    )
    assert settled["open_claim_count"] == 1
    assert settled["devices_total_count"] == 1
    assert settled["devices_in_stock_count"] == 1


def test_a_stale_dwelling_version_refuses_the_second_resolution_after_a_re_flag(api):
    """A third spelling pulls an already-adjudicated dwelling back into the cohort, so the
    resolver's version is stale and its earlier declared count survives the refusal intact.

    PRD: "A mismatch is rejected with `ERR_STALE_ADDRESS_VERSION` (HTTP 412). A resolved
    dwelling may legitimately be re-flagged and re-resolved with a different declared household
    count, so a stale resolver would otherwise decide against occupancy figures it never read."

    Design: Corner/cross_cutting_complexity_layers/stale_address_version_blocks_the_second_resolution
    """
    fx.set_clock(api, CLOCK)
    first, second = fx.duplicate_cohort(api, count=2)
    for dwelling in (first, second):
        refreshed = fx.refresh_address(api, dwelling["id"])
        assert_household_address(refreshed)
        assert refreshed["address_hash"] == COHORT_HASH, (
            f"both spellings canonicalise to one hash, got {refreshed['address_hash']!r}"
        )
        assert refreshed["status"] == "DUPLICATE_FLAGGED"
        assert refreshed["cohort_address_count"] == 2

    opening_version = fx.address_version(api, first["id"])
    resolved = validate_success(
        api.resolve_duplicate_address(
            first["id"],
            f.duplicate_resolution_payload(
                resolution="MULTI_HOUSEHOLD",
                expected_address_version=opening_version,
                declared_household_count=2,
                independent_household_worksheet_ref="WS-21",
            ),
            PROGRAM_ADMIN,
        )
    )
    assert resolved["status"] == "RESOLVED_MULTI_HOUSEHOLD"
    assert resolved["declared_household_count"] == 2
    assert resolved["max_permitted_benefit_slots"] == 2, (
        f"the permitted occupancy recomputes to the declared count, "
        f"got {resolved['max_permitted_benefit_slots']}"
    )
    stale_version = resolved["version"]
    assert stale_version == opening_version + 1

    third = validate_success(
        api.create_address(
            f.address_payload(
                address_line1="1200-N-MAIN-ST",
                unit_designator="APT4B",
                city="el paso",
                state_code="TX",
                postal_code="79901",
            ),
            PROGRAM_ADMIN,
        ),
        201,
    )
    assert third["status"] == "DUPLICATE_FLAGGED", (
        "a newly registered duplicate is born flagged rather than passing through UNVERIFIED"
    )
    assert third["cohort_address_count"] == 3

    refused = api.resolve_duplicate_address(
        first["id"],
        f.duplicate_resolution_payload(
            resolution="MULTI_HOUSEHOLD",
            expected_address_version=stale_version,
            declared_household_count=3,
            independent_household_worksheet_ref="WS-22",
        ),
        PROGRAM_ADMIN,
    )
    validate_error(refused, ApiErrorId.STALE_ADDRESS_VERSION.value, 412)

    re_flagged = fx.refresh_address(api, first["id"])
    assert re_flagged["status"] == "DUPLICATE_FLAGGED", (
        "the later arrival pulled the adjudicated dwelling back onto the re-entry edge"
    )
    assert re_flagged["max_permitted_benefit_slots"] == 1, (
        f"the re-flag strips the extra capacity, got {re_flagged['max_permitted_benefit_slots']}"
    )
    assert re_flagged["cohort_address_count"] == 3
    assert re_flagged["declared_household_count"] == 2, (
        "the earlier declared count is deliberately kept for the audit trail"
    )
    assert re_flagged["independent_household_worksheet_ref"] == "WS-21"
    fresh_version = re_flagged["version"]
    assert fresh_version == stale_version + 1, (
        f"the re-flag bumped the dwelling once, got {fresh_version} from {stale_version}"
    )

    re_resolved = validate_success(
        api.resolve_duplicate_address(
            first["id"],
            f.duplicate_resolution_payload(
                resolution="MULTI_HOUSEHOLD",
                expected_address_version=fresh_version,
                declared_household_count=3,
                independent_household_worksheet_ref="WS-22",
            ),
            PROGRAM_ADMIN,
        )
    )
    assert re_resolved["status"] == "RESOLVED_MULTI_HOUSEHOLD"
    assert re_resolved["declared_household_count"] == 3
    assert re_resolved["independent_household_worksheet_ref"] == "WS-22"
    assert re_resolved["max_permitted_benefit_slots"] == 3, (
        f"the second adjudication recomputes occupancy to three, "
        f"got {re_resolved['max_permitted_benefit_slots']}"
    )
    assert re_resolved["version"] == fresh_version + 1

    for peer in (second, third):
        untouched = fx.refresh_address(api, peer["id"])
        assert untouched["status"] == "DUPLICATE_FLAGGED", (
            "resolving one row of a cohort never resolves its peers"
        )
        assert untouched["max_permitted_benefit_slots"] == 1


def test_both_penalty_cut_offs_are_taken_from_the_extrapolation_at_the_exact_boundary(api):
    """One carrier extrapolates to exactly 500 and must take the middle rate, the other to
    exactly 1500 and must take the high rate; neither extrapolation equals its failed line.

    PRD: "Step three selects the penalty rate **from the extrapolated figure**, not from
    `final_amount_cents`: 0.05 while the extrapolated error is below 500 cents, 0.10 while it is
    at least 500 and below 1500, and 0.20 once it reaches 1500."

    Design: Corner/cross_cutting_complexity_layers/penalty_rate_tiers_flip_at_exactly_five_hundred_and_fifteen_hundred
    """
    fx.set_clock(api, JULY_FILING)
    carrier_a, carrier_b = fx.register_provider_pair(api, licensed_state_codes=["TX"])
    plan = [
        (carrier_a, JUNE_16),
        (carrier_a, JUNE_21),
        (carrier_b, JUNE_START),
        (carrier_b, JUNE_START),
        (carrier_b, JUNE_16),
    ]
    for index, (carrier, start) in enumerate(plan, start=1):
        address = fx.register_distinct_address(api, index)
        applicant = fx.eligible_applicant(api, address["id"])
        benefit = fx.enroll(
            api,
            carrier,
            applicant["subscriber"],
            applicant["check"],
            address,
            service_type="BROADBAND",
            benefit_start_date=start,
        )
        assert benefit["audit_risk_score"] == 0, (
            "every dwelling stands alone and no handset moved, so ranking falls through to "
            f"benefit_start_date, got {benefit['audit_risk_score']}"
        )

    claim_a = fx.file_claim(
        api, fx.draft_claim(api, carrier_a, "2026-06")["id"], carrier_a,
        certifying_officer_ref="OFFICER-25",
    )
    assert claim_a["final_amount_cents"] == 1000, (
        f"600 for fifteen days plus 400 for ten days, got {claim_a['final_amount_cents']}"
    )
    assert claim_a["variance_cents"] == 0
    assert claim_a["covered_enrollment_count"] == 2

    claim_b = fx.file_claim(
        api, fx.draft_claim(api, carrier_b, "2026-06")["id"], carrier_b,
        certifying_officer_ref="OFFICER-26",
    )
    assert claim_b["final_amount_cents"] == 3000, (
        f"1200 plus 1200 plus 600, got {claim_b['final_amount_cents']}"
    )
    assert claim_b["covered_enrollment_count"] == 3

    samples_a = fx.draw_samples(api, claim_a["id"], sample_size=2)
    assert [row["claimed_line_cents"] for row in samples_a] == [600, 400], (
        "the earlier benefit outranks the later one on benefit_start_date ascending, got "
        f"{[row['claimed_line_cents'] for row in samples_a]}"
    )
    samples_b = fx.draw_samples(api, claim_b["id"], sample_size=2)
    assert [row["claimed_line_cents"] for row in samples_b] == [1200, 1200]

    assert fx.adjudicate(
        api, samples_a[0]["id"], finding="COMPLIANT", finding_note="documentation complete"
    )["status"] == "ADJUDICATED_PASS"
    failed_a = fx.adjudicate(
        api,
        samples_a[1]["id"],
        finding="NON_USAGE_UNCURED",
        finding_note="no usage in the service month",
    )
    assert failed_a["status"] == "ADJUDICATED_FAIL"
    assert failed_a["disallowed_support_cents"] == 400, (
        f"the disallowed figure is the sampled line, not the extrapolation, "
        f"got {failed_a['disallowed_support_cents']}"
    )

    mid_tier = expected_recoupment(1000, 1, 2)
    assert mid_tier["extrapolated_cents"] == 500
    settled_a = fx.refresh_claim(api, claim_a["id"])
    assert settled_a["status"] == "AUDIT_FAILED"
    assert settled_a["failed_sample_count"] == 1
    assert settled_a["audit_sample_count"] == 2
    assert settled_a["penalty_cents"] == 50, (
        f"an extrapolation of exactly 500 takes the middle rate 0.10, "
        f"got a penalty of {settled_a['penalty_cents']}"
    )
    assert settled_a["recoupment_amount_cents"] == 550
    assert settled_a["net_payable_cents"] == 450
    assert settled_a["penalty_cents"] == mid_tier["penalty_cents"]
    assert settled_a["recoupment_amount_cents"] == mid_tier["recoupment_amount_cents"]
    assert settled_a["net_payable_cents"] == mid_tier["net_payable_cents"]
    assert settled_a["recoupment_amount_cents"] != failed_a["disallowed_support_cents"], (
        "the clawback extrapolates from a rate rather than recouping the failed line"
    )

    passing_b = fx.adjudicate(
        api, samples_b[0]["id"], finding="COMPLIANT", finding_note="documentation complete"
    )
    assert passing_b["status"] == "ADJUDICATED_PASS"
    mid_flight = fx.refresh_claim(api, claim_b["id"])
    assert mid_flight["status"] == "UNDER_AUDIT", (
        "the passing arm is a join, so it waits for the sample still sitting in DRAWN"
    )
    assert mid_flight["penalty_cents"] == 0
    assert mid_flight["net_payable_cents"] == 3000

    failed_b = fx.adjudicate(
        api,
        samples_b[1]["id"],
        finding="NON_USAGE_UNCURED",
        finding_note="no usage in the service month",
    )
    assert failed_b["status"] == "ADJUDICATED_FAIL"
    assert failed_b["disallowed_support_cents"] == 1200

    high_tier = expected_recoupment(3000, 1, 2)
    assert high_tier["extrapolated_cents"] == 1500
    settled_b = fx.refresh_claim(api, claim_b["id"])
    assert settled_b["status"] == "AUDIT_FAILED"
    assert settled_b["failed_sample_count"] == 1
    assert settled_b["audit_sample_count"] == 2
    assert settled_b["penalty_cents"] == 300, (
        f"an extrapolation of exactly 1500 crosses into the high rate 0.20, "
        f"got a penalty of {settled_b['penalty_cents']}"
    )
    assert settled_b["recoupment_amount_cents"] == 1800
    assert settled_b["net_payable_cents"] == 1200
    assert settled_b["penalty_cents"] == high_tier["penalty_cents"]
    assert settled_b["recoupment_amount_cents"] == high_tier["recoupment_amount_cents"]
    assert settled_b["net_payable_cents"] == high_tier["net_payable_cents"]
    assert settled_b["recoupment_amount_cents"] != failed_b["disallowed_support_cents"]

    assert_ledger_tuple(fx.refresh_provider(api, carrier_a["id"]), 1000, 550, 450, True)
    assert_ledger_tuple(fx.refresh_provider(api, carrier_b["id"]), 3000, 1800, 1200, True)

    for failure in (failed_a, failed_b):
        stranded = fx.refresh_enrollment(api, failure["enrollment_id"])
        assert stranded["benefit_status"] == "ACTIVE", (
            "an uncured-usage finding disallows the money without ending the benefit"
        )


def test_every_derived_field_is_already_settled_in_the_writes_own_response(api):
    """The issuance response, the filing response and the very next read of the neighbours all
    carry the recomputed figures, and a repeated read neither recomputes nor bumps a version.

    PRD: "The service is immediately consistent: when a request returns, every counter, flag and
    cascaded state it implies has already been written, and a subsequent read observes the
    settled world."

    Design: Corner/consistency_model/every_derived_field_is_current_in_the_writes_own_response
    """
    fx.set_clock(api, JULY_FILING)
    provider = fx.register_provider(api, licensed_state_codes=["TX"])
    agent = fx.provider_headers(provider)
    address = fx.register_distinct_address(api, 1)
    assert address["status"] == "UNVERIFIED"
    applicant = fx.eligible_applicant(api, address["id"])
    benefit = fx.enroll(
        api,
        provider,
        applicant["subscriber"],
        applicant["check"],
        address,
        service_type="VOICE",
        benefit_start_date=JUNE_START,
    )
    assert benefit["device_status"] == "AWAITING_DEVICE"
    assert benefit["audit_risk_score"] == 0
    handset = fx.stock_device(api, provider, model_tier="BASIC", unit_cost_cents=2100)
    assert handset["status"] == "IN_STOCK"

    issued = validate_success(
        api.issue_device(
            benefit["id"], f.device_issuance_payload(device_id=handset["id"]), agent
        )
    )
    assert_device(issued)
    assert issued["status"] == "ISSUED", (
        "the issuance response itself already carries the custody move"
    )
    assert issued["issued_enrollment_id"] == benefit["id"]
    assert_instant(issued["issued_at"], JULY_FILING, "issued_at")

    first_read = validate_success(api.get_enrollment(benefit["id"], PROGRAM_ADMIN))
    assert first_read["device_status"] == "DEVICE_ISSUED", (
        "the cross-entity effect needed no second write and no sweep"
    )
    assert first_read["device_issuance_count"] == 1
    assert_instant(first_read["last_device_issued_at"], JULY_FILING, "last_device_issued_at")
    assert first_read["audit_risk_score"] == 10, (
        f"one issuance weighs 10, got {first_read['audit_risk_score']}"
    )
    assert first_read["audit_risk_score"] == expected_risk_score(device_issuance_count=1)

    second_read = validate_success(api.get_enrollment(benefit["id"], PROGRAM_ADMIN))
    assert second_read["audit_risk_score"] == first_read["audit_risk_score"]
    assert second_read["version"] == first_read["version"], (
        f"repeating a read neither recomputes nor bumps anything, so the version holds at "
        f"{first_read['version']}, got {second_read['version']}"
    )

    carrier = validate_success(api.get_provider(provider["id"], PROGRAM_ADMIN))
    assert carrier["devices_total_count"] == 1
    assert carrier["devices_in_stock_count"] == 0, (
        f"the warehouse counters were current on the first read after the issuance, "
        f"got {carrier['devices_in_stock_count']} in stock"
    )
    assert carrier["devices_issued_count"] == 1
    assert carrier["claim_gross_cents"] == 0, "no claim has been filed yet"

    draft = validate_success(
        api.create_claim(
            f.claim_payload(
                provider_id=provider["id"],
                service_month="2026-06",
                expected_provider_version=carrier["version"],
            ),
            agent,
        ),
        201,
    )
    assert draft["provisional_amount_cents"] == 925
    assert draft["final_amount_cents"] == 0
    assert draft["variance_cents"] == 0
    assert fx.refresh_provider(api, provider["id"])["claim_gross_cents"] == 0, (
        "a draft contributes nothing to the ledger"
    )

    filed = validate_success(
        api.file_claim(draft["id"], f.claim_file_payload(certifying_officer_ref="OFFICER-27"), agent)
    )
    assert filed["status"] == "FILED", (
        "the filing response itself states the settled amount, so no re-read is needed"
    )
    assert filed["final_amount_cents"] == 925
    assert filed["variance_cents"] == 0
    assert_instant(filed["filed_at"], JULY_FILING, "filed_at")

    ledger = validate_success(api.get_provider(provider["id"], PROGRAM_ADMIN))
    assert_ledger_tuple(ledger, 925, 0, 925, False)
    assert ledger["open_claim_count"] == 1

    persisted = validate_success(api.get_claim(draft["id"], PROGRAM_ADMIN))
    assert persisted["status"] == "FILED"
    assert persisted["final_amount_cents"] == filed["final_amount_cents"]
    assert persisted["variance_cents"] == filed["variance_cents"], (
        "the persisted row equals what the write returned"
    )
