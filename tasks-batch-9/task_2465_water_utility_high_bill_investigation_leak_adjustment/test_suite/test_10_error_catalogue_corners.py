"""Reachability of the declared refusal codes across the high-bill workflow.

Every refusal this service can produce has to be reachable from a fixture a real
utility could build, and it has to be the refusal the rejection ladder names
rather than a neighbouring one. The tests below drive one legitimate estate at a
time — a billing calendar, a metered account, an investigation, an instalment
plan, a board appeal — and aim a single malformed-but-well-typed request at it,
then re-read the entity and the append-only ledger to confirm the refusal moved
nothing. Where two codes could plausibly answer the same request, the assertion
pins the one the ladder puts first, and where a rule has two sides the accepted
neighbour is exercised beside the refused one.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    CLERK_HEADERS,
    CSR_ALT_HEADERS,
    CSR_HEADERS,
    SUPERVISOR_HEADERS,
    TECHNICIAN_HEADERS,
    assertions,
    factories,
    fixtures,
    make_clerk_headers,
    make_csr_headers,
)

# Identifiers that resolve to nothing in any collection.
UNKNOWN_PERIOD_ID = "00000000-0000-4000-8000-000000000001"
UNKNOWN_TEST_REQUEST_ID = "00000000-0000-4000-8000-000000000002"
UNKNOWN_PROOF_ID = "00000000-0000-4000-8000-000000000003"
UNKNOWN_ARRANGEMENT_ID = "00000000-0000-4000-8000-000000000004"
UNKNOWN_APPEAL_ID = "00000000-0000-4000-8000-000000000005"


# ---------------------------------------------------------------------------
# Shared estate builders
# ---------------------------------------------------------------------------
def _assert_error_envelope_only(error_data):
    """A refusal body carries the two error fields and nothing else."""
    assert sorted(error_data) == ["error_id", "message"], (
        f"error envelope carried {sorted(error_data)}"
    )


def _total_count(response):
    """The pre-window row count of a list response."""
    _rows, meta = validate_paginated(response)
    return meta["total_count"]


def _intake_estate(api):
    """A billed meter on a finished period, a bare meter, and one live period.

    ``billed`` carries two reads and one ISSUED bill for the finished period, so
    the duplicate guard has something to collide with. ``bare`` carries only its
    opening read, so a backward read has a live predecessor to fall below. The
    2026-08 period has not ended at the default clock instant.
    """
    fixtures.set_clock(api)
    schedule = fixtures.create_rate_schedule(api)
    finished = fixtures.create_billing_period(
        api,
        period_code="2025-06",
        start_date="2025-06-01",
        end_date="2025-06-30",
        season="SUMMER",
        rebilling_deadline_date="2026-12-31",
    )
    live = fixtures.create_billing_period(
        api,
        period_code="2026-08",
        start_date="2026-08-01",
        end_date="2026-08-31",
        season="SUMMER",
        rebilling_deadline_date="2027-02-28",
    )
    billed_account = fixtures.create_account(api, schedule["id"])
    billed_meter = fixtures.create_master_meter(
        api, billed_account["id"], initial_register_value=100000
    )
    fixtures.post_reading(api, billed_meter["id"], "2025-05-31", 100000)
    fixtures.post_reading(api, billed_meter["id"], "2025-06-30", 104000)
    bill = fixtures.generate_and_issue_bill(
        api, billed_account["id"], finished["id"], billed_meter["id"]
    )

    bare_account = fixtures.create_account(api, schedule["id"])
    bare_meter = fixtures.create_master_meter(
        api, bare_account["id"], initial_register_value=100000
    )
    opening = fixtures.post_reading(api, bare_meter["id"], "2025-05-31", 100000)
    return {
        "finished_period_id": finished["id"],
        "live_period_id": live["id"],
        "billed_account_id": billed_account["id"],
        "billed_meter_id": billed_meter["id"],
        "bill": bill,
        "bill_id": bill["id"],
        "bare_account_id": bare_account["id"],
        "bare_meter_id": bare_meter["id"],
        "opening_read_id": opening["id"],
    }


def _two_billed_accounts(api):
    """Two accounts on one period, each with its own ISSUED 4000-gallon bill."""
    fixtures.set_clock(api)
    schedule = fixtures.create_rate_schedule(api)
    period = fixtures.create_billing_period(
        api,
        period_code="2025-06",
        start_date="2025-06-01",
        end_date="2025-06-30",
        season="SUMMER",
        rebilling_deadline_date="2026-12-31",
    )
    built = []
    for _ in range(2):
        account = fixtures.create_account(api, schedule["id"])
        meter = fixtures.create_master_meter(
            api, account["id"], initial_register_value=100000
        )
        fixtures.post_reading(api, meter["id"], "2025-05-31", 100000)
        fixtures.post_reading(api, meter["id"], "2025-06-30", 104000)
        bill = fixtures.generate_and_issue_bill(
            api, account["id"], period["id"], meter["id"]
        )
        built.append({"account_id": account["id"], "bill_id": bill["id"]})
    return {
        "account_id": built[0]["account_id"],
        "bill_id": built[0]["bill_id"],
        "other_account_id": built[1]["account_id"],
        "other_bill_id": built[1]["bill_id"],
    }


def _second_period_credit_estate(api):
    """A posted credit on the 2026-07 bill and a second submitted credit on 2026-08.

    The first credit is approved by ``sup-1`` off a determination recorded by
    ``csr-1``, so the second approval cannot be refused for segregation of
    duties. The August bill consumes exactly its baseline, so the second credit
    is worth nothing and only the rolling-window ceiling can refuse it.
    """
    ctx = fixtures.posted_adjustment_case(api)
    august = fixtures.create_billing_period(
        api,
        period_code="2026-08",
        start_date="2026-08-01",
        end_date="2026-08-31",
        season="SUMMER",
        rebilling_deadline_date="2027-02-28",
    )
    fixtures.set_clock(api, "2026-09-05T00:00:00Z")
    fixtures.post_reading(api, ctx["meter_id"], "2026-08-31", 157000)
    august_bill = fixtures.generate_and_issue_bill(
        api, ctx["account_id"], august["id"], ctx["meter_id"]
    )

    second = fixtures.open_investigation(api, august_bill["id"], CSR_HEADERS)
    fixtures.request_evidence(api, second["id"], CSR_HEADERS)
    proof = fixtures.submit_repair_proof(
        api, second["id"], "TOILET", CSR_HEADERS, repair_date="2026-08-20"
    )
    fixtures.verify_repair_proof(api, proof["id"], CSR_HEADERS)
    second = fixtures.determine(api, second["id"], "CUSTOMER_SIDE_LEAK", CSR_HEADERS)
    second_adjustment = fixtures.draft_adjustment(
        api,
        second["id"],
        august_bill["id"],
        "TOILET",
        second["version"],
        CSR_HEADERS,
    )
    second_adjustment = fixtures.submit_adjustment(
        api, second_adjustment["id"], CSR_HEADERS
    )
    ctx.update(
        {
            "august_period_id": august["id"],
            "august_bill_id": august_bill["id"],
            "second_investigation_id": second["id"],
            "second_adjustment_id": second_adjustment["id"],
            "second_adjustment": second_adjustment,
        }
    )
    return ctx


def _closed_case_under_appeal(api):
    """A closed investigation whose appeal was filed by the operator ``u-shared``.

    No evidence round is consumed before the closure and no determination is
    ever recorded, so the only user identifier a hearing officer can collide
    with is the filer's.
    """
    ctx = fixtures.upheld_bill_case(api, request_first_round=False)
    filer_headers = make_csr_headers("u-shared")
    appeal = fixtures.file_appeal(api, ctx["investigation_id"], filer_headers)
    ctx.update(
        {
            "appeal": appeal,
            "appeal_id": appeal["id"],
            "filer_headers": filer_headers,
            "filed_by_user_id": "u-shared",
        }
    )
    return ctx


def _remanded_case_on_a_second_appeal(api):
    """One remand absorbed, the case closed again, and a second hearing docketed."""
    ctx = _closed_case_under_appeal(api)
    fixtures.schedule_hearing(api, ctx["appeal_id"], "2026-08-11")
    fixtures.set_clock(api, "2026-08-11T15:00:00Z")
    fixtures.record_board_decision(api, ctx["appeal_id"], "REMAND", CLERK_HEADERS)

    remanded = fixtures.fetch_investigation(api, ctx["investigation_id"])
    assertions.assert_fields(
        remanded, status="EVIDENCE_REQUESTED", remand_count=1, evidence_round_count=1
    )
    validate_success(
        api.close_investigation_no_adjustment(
            ctx["investigation_id"],
            CSR_HEADERS,
            factories.close_no_adjustment_payload(),
        )
    )
    second_appeal = fixtures.file_appeal(
        api, ctx["investigation_id"], CSR_ALT_HEADERS
    )
    second_appeal = fixtures.schedule_hearing(api, second_appeal["id"], "2026-08-21")
    fixtures.set_clock(api, "2026-08-21T14:00:00Z")
    ctx["second_appeal_id"] = second_appeal["id"]
    ctx["second_appeal"] = second_appeal
    return ctx


def _investigation_test_estate(api):
    """An OPEN investigation plus a meter owned by an unrelated account.

    The investigation is left in ``OPEN`` — no evidence round has been asked for
    — so a closing meter test cannot escalate it and the account ledger holds
    exactly its four bill charges.
    """
    ctx = fixtures.investigation_case(api, request_first_round=False)
    other_account = fixtures.create_account(api, ctx["rate_schedule_id"])
    other_meter = fixtures.create_master_meter(
        api, other_account["id"], initial_register_value=100000
    )
    ctx["other_account_id"] = other_account["id"]
    ctx["other_meter_id"] = other_meter["id"]
    return ctx


# ===========================================================================
# Unknown path identifiers: each collection owns its own 404 code
# ===========================================================================


def test_reads_of_unknown_path_ids_report_the_owning_collections_not_found_code(api):
    """PRD §2.7: "**Path resource existence**, resolved left to right across the URL so the leftmost unresolvable identifier is the one reported → `ERR_RATE_SCHEDULE_NOT_FOUND`, `ERR_BILLING_PERIOD_NOT_FOUND`, `ERR_SERVICE_ACCOUNT_NOT_FOUND`, `ERR_METER_NOT_FOUND`, `ERR_METER_READING_NOT_FOUND`, `ERR_BILL_NOT_FOUND`, `ERR_INVESTIGATION_NOT_FOUND`, `ERR_METER_TEST_REQUEST_NOT_FOUND`, `ERR_REPAIR_PROOF_NOT_FOUND`, `ERR_LEAK_ADJUSTMENT_NOT_FOUND`, `ERR_PAYMENT_ARRANGEMENT_NOT_FOUND` or `ERR_BOARD_APPEAL_NOT_FOUND`, all 404."

    PRD §2.2: "The `meta` object for error responses contains only `api_request_id` and `api_request_timestamp`."

    Design: Corner/errors/corner_error_unknown_path_ids_return_the_entity_specific_not_found_code
    """
    fixtures.set_clock(api)

    probes = [
        (
            api.get_billing_period(UNKNOWN_PERIOD_ID, CSR_HEADERS),
            "ERR_BILLING_PERIOD_NOT_FOUND",
        ),
        (
            api.get_meter_test_request(UNKNOWN_TEST_REQUEST_ID, CSR_HEADERS),
            "ERR_METER_TEST_REQUEST_NOT_FOUND",
        ),
        (
            api.get_repair_proof(UNKNOWN_PROOF_ID, CSR_HEADERS),
            "ERR_REPAIR_PROOF_NOT_FOUND",
        ),
        (
            api.get_payment_arrangement(UNKNOWN_ARRANGEMENT_ID, CSR_HEADERS),
            "ERR_PAYMENT_ARRANGEMENT_NOT_FOUND",
        ),
        (
            api.get_board_appeal(UNKNOWN_APPEAL_ID, CSR_HEADERS),
            "ERR_BOARD_APPEAL_NOT_FOUND",
        ),
    ]
    for response, expected_error_id in probes:
        error_data = validate_error(response, expected_error_id)
        _assert_error_envelope_only(error_data)


def test_action_endpoints_resolve_the_path_id_before_reading_the_body(api):
    """PRD §2.7: "Checks are evaluated in a strict ascending order and the **first** violated check short-circuits the request; nothing after it runs."

    PRD §2.7: "**Path resource existence**, resolved left to right across the URL so the leftmost unresolvable identifier is the one reported → `ERR_RATE_SCHEDULE_NOT_FOUND`, `ERR_BILLING_PERIOD_NOT_FOUND`, `ERR_SERVICE_ACCOUNT_NOT_FOUND`, `ERR_METER_NOT_FOUND`, `ERR_METER_READING_NOT_FOUND`, `ERR_BILL_NOT_FOUND`, `ERR_INVESTIGATION_NOT_FOUND`, `ERR_METER_TEST_REQUEST_NOT_FOUND`, `ERR_REPAIR_PROOF_NOT_FOUND`, `ERR_LEAK_ADJUSTMENT_NOT_FOUND`, `ERR_PAYMENT_ARRANGEMENT_NOT_FOUND` or `ERR_BOARD_APPEAL_NOT_FOUND`, all 404."

    Design: Corner/errors/corner_error_unknown_path_ids_return_the_entity_specific_not_found_code
    """
    fixtures.set_clock(api)

    # Every body here is well formed, so a schema or state refusal cannot mask
    # the missing path row.
    bench = validate_error(
        api.record_bench_result(
            UNKNOWN_TEST_REQUEST_ID,
            factories.bench_result_payload(99.0, 100.0, 100.5),
            TECHNICIAN_HEADERS,
        ),
        "ERR_METER_TEST_REQUEST_NOT_FOUND",
    )
    _assert_error_envelope_only(bench)

    verify = validate_error(
        api.verify_repair_proof(UNKNOWN_PROOF_ID, CSR_HEADERS),
        "ERR_REPAIR_PROOF_NOT_FOUND",
    )
    _assert_error_envelope_only(verify)

    activate = validate_error(
        api.activate_payment_arrangement(UNKNOWN_ARRANGEMENT_ID, CSR_HEADERS),
        "ERR_PAYMENT_ARRANGEMENT_NOT_FOUND",
    )
    _assert_error_envelope_only(activate)

    # The hearing_date is far enough out to satisfy the notice rule, so a 422
    # cannot be substituted for the 404.
    docket = validate_error(
        api.schedule_hearing(
            UNKNOWN_APPEAL_ID,
            factories.hearing_schedule_payload("2026-09-01"),
            CLERK_HEADERS,
        ),
        "ERR_BOARD_APPEAL_NOT_FOUND",
    )
    _assert_error_envelope_only(docket)


# ===========================================================================
# Bill generation and read intake guards
# ===========================================================================


def test_bill_generation_before_its_period_has_ended_is_refused(api):
    """PRD §3.2: "The period must already be over — today's date on the logical clock must be strictly later than the period's `end_date` — else `ERR_BILLING_PERIOD_NOT_ENDED`."

    Design: Corner/errors/corner_error_bill_generation_and_read_intake_guards_all_fire
    """
    ctx = _intake_estate(api)

    validate_error(
        api.create_bill(
            factories.bill_payload(
                ctx["billed_account_id"], ctx["live_period_id"], ctx["billed_meter_id"]
            ),
            SUPERVISOR_HEADERS,
        ),
        "ERR_BILLING_PERIOD_NOT_ENDED",
    )

    assert (
        _total_count(
            api.list_bills(
                SUPERVISOR_HEADERS, {"period_id": ctx["live_period_id"], "limit": 100}
            )
        )
        == 0
    )


def test_second_live_bill_for_the_same_meter_and_period_is_refused(api):
    """PRD §3.2: "And no bill for the same meter and period may already exist in any state other than `REBILLED`, else `ERR_DUPLICATE_BILL_FOR_PERIOD`."

    Design: Corner/errors/corner_error_bill_generation_and_read_intake_guards_all_fire
    """
    ctx = _intake_estate(api)

    validate_error(
        api.create_bill(
            factories.bill_payload(
                ctx["billed_account_id"],
                ctx["finished_period_id"],
                ctx["billed_meter_id"],
            ),
            SUPERVISOR_HEADERS,
        ),
        "ERR_DUPLICATE_BILL_FOR_PERIOD",
    )

    assert (
        _total_count(
            api.list_bills(
                SUPERVISOR_HEADERS,
                {
                    "meter_id": ctx["billed_meter_id"],
                    "period_id": ctx["finished_period_id"],
                    "limit": 100,
                },
            )
        )
        == 1
    )
    survivor = fixtures.fetch_bill(api, ctx["bill_id"])
    assertions.assert_fields(survivor, billing_status="ISSUED", total_charge_cents=5210)
    assertions.assert_version(survivor, ctx["bill"]["version"])


def test_reading_dated_after_the_logical_clock_is_refused(api):
    """PRD §3.1: "A read may not be dated in the future: if `read_date` falls after today's date on the logical clock the post is refused with `ERR_READ_DATE_IN_FUTURE`."

    Design: Corner/errors/corner_error_bill_generation_and_read_intake_guards_all_fire
    """
    ctx = _intake_estate(api)

    validate_error(
        api.create_meter_reading(
            factories.meter_reading_payload(
                ctx["bare_meter_id"], "2026-09-01", 108000
            ),
            TECHNICIAN_HEADERS,
        ),
        "ERR_READ_DATE_IN_FUTURE",
    )

    assert (
        _total_count(
            api.list_meter_readings(
                TECHNICIAN_HEADERS, {"meter_id": ctx["bare_meter_id"], "limit": 100}
            )
        )
        == 1
    )


def test_actual_read_below_the_latest_live_register_value_is_refused(api):
    """PRD §3.1: "Registers only advance, so an `ACTUAL` or `ESTIMATED` read whose `reading_value` is below the `reading_value` of the latest live read on that meter — or below the meter's `initial_register_value` when no read exists yet — is refused with `ERR_NEGATIVE_CONSUMPTION`."

    Design: Corner/errors/corner_error_bill_generation_and_read_intake_guards_all_fire
    """
    ctx = _intake_estate(api)

    validate_error(
        api.create_meter_reading(
            factories.meter_reading_payload(ctx["bare_meter_id"], "2025-06-30", 99000),
            TECHNICIAN_HEADERS,
        ),
        "ERR_NEGATIVE_CONSUMPTION",
    )

    rows = fixtures.live_readings(api, ctx["bare_meter_id"])
    assert [row["reading_value"] for row in rows] == [100000]


def test_corrected_read_may_restate_the_register_downward(api):
    """PRD §3.1: "A `CORRECTED` read is exempt from that check because its whole purpose is to restate a figure downward or upward; in exchange it must name `corrects_reading_id`, the read it supersedes, and `corrects_reading_id` is forbidden on `ACTUAL` and `ESTIMATED` reads."

    PRD §3.1: "Liveness is tracked by `superseded_by_reading_id`: a row whose `superseded_by_reading_id` is null is live, and posting a `CORRECTED` read sets that field on the row named by `corrects_reading_id` to the new row's identifier."

    Design: Corner/errors/corner_error_bill_generation_and_read_intake_guards_all_fire
    """
    ctx = _intake_estate(api)
    forward = fixtures.post_reading(api, ctx["bare_meter_id"], "2025-06-30", 104000)

    corrected = validate_success(
        api.create_meter_reading(
            factories.corrected_reading_payload(
                ctx["bare_meter_id"], "2025-06-30", 102000, forward["id"]
            ),
            TECHNICIAN_HEADERS,
        ),
        201,
    )
    assertions.assert_fields(
        corrected,
        read_type="CORRECTED",
        reading_value=102000,
        corrects_reading_id=forward["id"],
        consumption_since_prior_gallons=2000,
    )

    superseded = validate_success(
        api.get_meter_reading(forward["id"], TECHNICIAN_HEADERS)
    )
    assertions.assert_fields(superseded, superseded_by_reading_id=corrected["id"])

    live = fixtures.live_readings(api, ctx["bare_meter_id"])
    assert [row["reading_value"] for row in live] == [100000, 102000]


# ===========================================================================
# Drafting a credit: the evidentiary precondition
# ===========================================================================


def test_credit_draft_without_a_verified_proof_is_refused(api):
    """PRD §3.6: "Unless the determination is `METER_ERROR`, at least one repair proof on the investigation must be `VERIFIED`, else `ERR_REPAIR_PROOF_REQUIRED`; and unless the determination is `METER_ERROR`, the supplied `leak_type` must equal the `leak_type` of at least one such `VERIFIED` proof, else `ERR_LEAK_TYPE_MISMATCH`."

    PRD §2.7: "Within tier 12, note that leak-type coherence is checked before bill coherence, matching the field order of the drafting payload."

    Design: Corner/errors/corner_error_leak_adjustment_without_a_verified_proof_is_refused
    """
    ctx = fixtures.proof_case(api, leak_type="IRRIGATION", verify=False)
    investigation = fixtures.determine(
        api, ctx["investigation_id"], "IRRIGATION_USE", ctx["rep_headers"]
    )
    assertions.assert_fields(
        investigation, status="DETERMINED", leak_determination="IRRIGATION_USE"
    )
    current_version = investigation["version"]

    # The token was read back from the determination response, so priority 7 is
    # satisfied and the refusal can only be the business rule.
    validate_error(
        api.create_leak_adjustment(
            factories.leak_adjustment_payload(
                ctx["investigation_id"], ctx["bill_id"], "IRRIGATION", current_version
            ),
            ctx["rep_headers"],
        ),
        "ERR_REPAIR_PROOF_REQUIRED",
    )

    assert (
        _total_count(
            api.list_leak_adjustments(
                CSR_HEADERS,
                {"investigation_id": ctx["investigation_id"], "limit": 100},
            )
        )
        == 0
    )
    after = fixtures.fetch_investigation(api, ctx["investigation_id"])
    assertions.assert_fields(after, status="DETERMINED")
    assertions.assert_version(after, current_version)
    assertions.assert_fields(
        fixtures.fetch_bill(api, ctx["bill_id"]),
        billing_status="UNDER_INVESTIGATION",
        adjusted_total_cents=44939,
    )


def test_proof_cannot_be_verified_once_the_determination_is_recorded(api):
    """PRD §3.3: "A representative reviews each proof while the investigation is in `EVIDENCE_UNDER_REVIEW`."

    PRD §2.7: "**State preconditions.** The subject entity must sit in a state from which the requested transition exists, and every cross-entity state precondition of that transition must hold → `ERR_INVALID_STATE_TRANSITION` (409) on every action operation."

    Design: Corner/errors/corner_error_leak_adjustment_without_a_verified_proof_is_refused
    """
    ctx = fixtures.proof_case(api, leak_type="IRRIGATION", verify=False)
    fixtures.determine(api, ctx["investigation_id"], "IRRIGATION_USE", ctx["rep_headers"])

    validate_error(
        api.verify_repair_proof(ctx["proof_id"], ctx["rep_headers"]),
        "ERR_INVALID_STATE_TRANSITION",
    )

    proof = validate_success(api.get_repair_proof(ctx["proof_id"], CSR_HEADERS))
    assertions.assert_fields(proof, status="SUBMITTED")
    assertions.assert_null_fields(proof, "verified_by_user_id")


# ===========================================================================
# Drafting a credit: the two cross-row referential guards
# ===========================================================================


def test_credit_draft_pointed_at_another_bill_of_the_account_is_refused(api):
    """PRD §3.6: "The supplied `bill_id` must equal the investigation's own `bill_id`, else `ERR_ADJUSTMENT_BILL_MISMATCH`."

    Design: Corner/errors/corner_error_leak_adjustment_referential_guards_bill_and_leak_type
    """
    ctx = fixtures.determined_case(api)
    other_bill_id = ctx["history_bill_ids"][2]
    token = fixtures.investigation_version(api, ctx["investigation_id"])

    # The leak_type matches the verified proof, so the earlier tier-12 check
    # passes and only the bill reference can be at fault.
    validate_error(
        api.create_leak_adjustment(
            factories.leak_adjustment_payload(
                ctx["investigation_id"], other_bill_id, "SERVICE_LINE", token
            ),
            ctx["rep_headers"],
        ),
        "ERR_ADJUSTMENT_BILL_MISMATCH",
    )

    assert (
        _total_count(
            api.list_leak_adjustments(
                CSR_HEADERS,
                {"investigation_id": ctx["investigation_id"], "limit": 100},
            )
        )
        == 0
    )
    after = fixtures.fetch_investigation(api, ctx["investigation_id"])
    assertions.assert_fields(after, status="DETERMINED")
    assertions.assert_version(after, token)


def test_credit_draft_naming_an_unproven_leak_type_is_refused(api):
    """PRD §3.6: "Unless the determination is `METER_ERROR`, at least one repair proof on the investigation must be `VERIFIED`, else `ERR_REPAIR_PROOF_REQUIRED`; and unless the determination is `METER_ERROR`, the supplied `leak_type` must equal the `leak_type` of at least one such `VERIFIED` proof, else `ERR_LEAK_TYPE_MISMATCH`."

    Design: Corner/errors/corner_error_leak_adjustment_referential_guards_bill_and_leak_type
    """
    ctx = fixtures.determined_case(api)
    token = fixtures.investigation_version(api, ctx["investigation_id"])

    validate_error(
        api.create_leak_adjustment(
            factories.leak_adjustment_payload(
                ctx["investigation_id"], ctx["bill_id"], "TOILET", token
            ),
            ctx["rep_headers"],
        ),
        "ERR_LEAK_TYPE_MISMATCH",
    )

    assert (
        _total_count(
            api.list_leak_adjustments(
                CSR_HEADERS,
                {"investigation_id": ctx["investigation_id"], "limit": 100},
            )
        )
        == 0
    )
    after = fixtures.fetch_investigation(api, ctx["investigation_id"])
    assertions.assert_fields(after, status="DETERMINED")
    assertions.assert_version(after, token)


def test_refused_drafts_leave_the_investigation_version_token_spendable(api):
    """PRD §2.6: "A successful create increments the investigation's `version` by one."

    PRD §3.6: "Buried leaks — `SERVICE_LINE` and `UNDERGROUND` — take `BASELINE_REBILL`, where the whole excess is forgiven and the bill is simply rewritten to the baseline: `water_credit_cents` is `water_charge_cents` minus the water charge that consumption of exactly `seasonal_baseline_gallons` in that same `season` would have produced, again with any negative result treated as zero."

    Design: Corner/errors/corner_error_leak_adjustment_referential_guards_bill_and_leak_type
    """
    ctx = fixtures.determined_case(api)
    token = fixtures.investigation_version(api, ctx["investigation_id"])

    validate_error(
        api.create_leak_adjustment(
            factories.leak_adjustment_payload(
                ctx["investigation_id"], ctx["history_bill_ids"][2], "SERVICE_LINE", token
            ),
            ctx["rep_headers"],
        ),
        "ERR_ADJUSTMENT_BILL_MISMATCH",
    )
    validate_error(
        api.create_leak_adjustment(
            factories.leak_adjustment_payload(
                ctx["investigation_id"], ctx["bill_id"], "TOILET", token
            ),
            ctx["rep_headers"],
        ),
        "ERR_LEAK_TYPE_MISMATCH",
    )

    # The very same token is still current, which is only true if neither
    # refusal mutated the parent aggregate.
    adjustment = validate_success(
        api.create_leak_adjustment(
            factories.leak_adjustment_payload(
                ctx["investigation_id"], ctx["bill_id"], "SERVICE_LINE", token
            ),
            ctx["rep_headers"],
        ),
        201,
    )
    assertions.assert_credit_breakdown(
        adjustment,
        status="DRAFT",
        variant_applied="BASELINE_REBILL",
        excess_gallons=37000,
        water_credit_cents=34849,
        sewer_relief_gallons=8000,
        sewer_credit_cents=4880,
        gross_credit_cents=39729,
        cap_cents=26963,
        capped_credit_cents=26963,
        cap_applied=True,
        admin_fee_charged_cents=0,
        net_credit_cents=26963,
    )
    after = fixtures.fetch_investigation(api, ctx["investigation_id"])
    assertions.assert_fields(after, status="ADJUSTMENT_PENDING")
    assertions.assert_version(after, token + 1)


# ===========================================================================
# The once-per-rolling-window credit ceiling
# ===========================================================================


def test_second_credit_inside_the_rolling_window_is_refused_at_approval(api):
    """PRD §3.7: "It is available only from `PENDING_APPROVAL`; the acting `X-User-ID` must differ from the investigation's `determination_by_user_id`, else `ERR_SEGREGATION_OF_DUTIES`; the bill's period must not be `LOCKED`, else `ERR_BILLING_PERIOD_LOCKED`; and a once-per-period ceiling applies — no other leak adjustment on the same account may already hold `APPROVED` or `POSTED` status with its bill's period `end_date` falling inside the rolling twelve-month window ending at this adjustment's bill's period `end_date`, excluding whichever row this adjustment names in `supersedes_adjustment_id`, else `ERR_LEAK_ADJUSTMENT_CAP_EXCEEDED`."

    PRD §3.2: "Bills in `DRAFT`, `UNDER_INVESTIGATION`, `REBILL_PENDING` or `REBILLED` never qualify, and neither do anomaly-flagged or estimated bills — the baseline must be built from settled, actually-read, ordinary periods."

    Design: Corner/errors/corner_error_second_adjustment_inside_the_rolling_window_is_refused_at_approval
    """
    ctx = _second_period_credit_estate(api)

    # The August bill sits exactly on its baseline, so the credit it carries is
    # zero and the arithmetic cannot be the reason for a refusal.
    august_bill = fixtures.fetch_bill(api, ctx["august_bill_id"])
    assertions.assert_fields(
        august_bill,
        consumption_gallons=4000,
        seasonal_baseline_gallons=4000,
        baseline_sample_count=3,
        anomaly_flag=False,
    )
    assertions.assert_credit_breakdown(
        ctx["second_adjustment"],
        status="PENDING_APPROVAL",
        excess_gallons=0,
        net_credit_cents=0,
        supersedes_adjustment_id=None,
    )

    validate_error(
        api.approve_leak_adjustment(
            ctx["second_adjustment_id"], SUPERVISOR_HEADERS
        ),
        "ERR_LEAK_ADJUSTMENT_CAP_EXCEEDED",
    )

    refused = fixtures.fetch_adjustment(api, ctx["second_adjustment_id"])
    assertions.assert_fields(refused, status="PENDING_APPROVAL")
    assertions.assert_null_fields(refused, "approved_by_user_id", "posted_at")
    assertions.assert_fields(
        fixtures.fetch_investigation(api, ctx["second_investigation_id"]),
        status="ADJUSTMENT_PENDING",
    )
    assertions.assert_fields(
        fixtures.fetch_bill(api, ctx["august_bill_id"]),
        billing_status="UNDER_INVESTIGATION",
    )

    entries = assertions.ledger_entries(api, ctx["account_id"], CSR_HEADERS)
    assertions.assert_source_kinds(
        entries,
        [
            "BILL_CHARGE",
            "BILL_CHARGE",
            "BILL_CHARGE",
            "BILL_CHARGE",
            "LEAK_ADJUSTMENT_CREDIT",
            "BILL_CHARGE",
        ],
    )
    account = fixtures.fetch_account(api, ctx["account_id"])
    assertions.assert_account_state(account, balance_cents=38816)
    assertions.assert_balance_is_ledger_sum(account, entries)


# ===========================================================================
# Instalment-plan intake: the fiscal and referential guards
# ===========================================================================


def test_down_payment_outside_the_declared_bounds_is_refused(api):
    """PRD §3.8: "`down_payment_cents` must be at least twenty percent of `total_amount_cents` — computed as `total_amount_cents` multiplied by two thousand basis points, divided by ten thousand, rounded half up — and must not exceed `total_amount_cents`; either violation returns `ERR_DOWN_PAYMENT_TOO_LOW`."

    Design: Corner/errors/corner_error_payment_arrangement_fiscal_and_referential_guards_all_fire
    """
    ctx = _two_billed_accounts(api)
    token = fixtures.account_version(api, ctx["account_id"])

    # 1042 is the rounded twenty percent floor of 5210, so 1041 is one cent short.
    validate_error(
        api.create_payment_arrangement(
            factories.payment_arrangement_payload(
                ctx["account_id"], ctx["bill_id"], 5210, 1041, 4, token
            ),
            CSR_HEADERS,
        ),
        "ERR_DOWN_PAYMENT_TOO_LOW",
    )
    # The same rule carries the upper bound: a down payment above the total.
    validate_error(
        api.create_payment_arrangement(
            factories.payment_arrangement_payload(
                ctx["account_id"], ctx["bill_id"], 5210, 5211, 4, token
            ),
            CSR_HEADERS,
        ),
        "ERR_DOWN_PAYMENT_TOO_LOW",
    )

    assert (
        _total_count(
            api.list_payment_arrangements(
                CSR_HEADERS, {"account_id": ctx["account_id"], "limit": 100}
            )
        )
        == 0
    )
    assertions.assert_account_state(
        fixtures.fetch_account(api, ctx["account_id"]), balance_cents=5210
    )


def test_thirteen_installments_is_refused_before_any_fiscal_rule(api):
    """PRD §3.8: "Four business rules guard it. `installment_count` may not exceed twelve, else `ERR_INSTALLMENT_LIMIT_EXCEEDED`."

    Design: Corner/errors/corner_error_payment_arrangement_fiscal_and_referential_guards_all_fire
    """
    ctx = _two_billed_accounts(api)
    token = fixtures.account_version(api, ctx["account_id"])

    # The down payment in this call is exactly the floor, so no fiscal rule
    # competes with the count limit.
    validate_error(
        api.create_payment_arrangement(
            factories.payment_arrangement_payload(
                ctx["account_id"], ctx["bill_id"], 5210, 1042, 13, token
            ),
            CSR_HEADERS,
        ),
        "ERR_INSTALLMENT_LIMIT_EXCEEDED",
    )

    assert (
        _total_count(
            api.list_payment_arrangements(
                CSR_HEADERS, {"account_id": ctx["account_id"], "limit": 100}
            )
        )
        == 0
    )


def test_plan_financing_another_accounts_bill_is_refused(api):
    """PRD §3.8: "The financed bill must belong to the named account, and when an `investigation_id` is supplied that investigation must belong to it too, else `ERR_ARRANGEMENT_ACCOUNT_MISMATCH`."

    Design: Corner/errors/corner_error_payment_arrangement_fiscal_and_referential_guards_all_fire
    """
    ctx = _two_billed_accounts(api)
    token = fixtures.account_version(api, ctx["account_id"])

    validate_error(
        api.create_payment_arrangement(
            factories.payment_arrangement_payload(
                ctx["account_id"], ctx["other_bill_id"], 5210, 1042, 4, token
            ),
            CSR_HEADERS,
        ),
        "ERR_ARRANGEMENT_ACCOUNT_MISMATCH",
    )

    assert (
        _total_count(
            api.list_payment_arrangements(
                CSR_HEADERS, {"account_id": ctx["account_id"], "limit": 100}
            )
        )
        == 0
    )
    assert (
        _total_count(
            api.list_payment_arrangements(
                CSR_HEADERS, {"account_id": ctx["other_account_id"], "limit": 100}
            )
        )
        == 0
    )


def test_plan_total_that_does_not_match_the_bill_is_refused(api):
    """PRD §3.8: "And `total_amount_cents` must equal the financed bill's `adjusted_total_cents` at the time of proposal, else `ERR_ARRANGEMENT_AMOUNT_MISMATCH`, so a plan can never finance a figure the credit workflow has already superseded."

    PRD §2.7: "Within tier 13, arrangement proposal evaluates the down-payment floor before the financed-amount match."

    Design: Corner/errors/corner_error_payment_arrangement_fiscal_and_referential_guards_all_fire
    """
    ctx = _two_billed_accounts(api)
    token = fixtures.account_version(api, ctx["account_id"])
    assertions.assert_fields(
        fixtures.fetch_bill(api, ctx["bill_id"]), adjusted_total_cents=5210
    )

    # 1042 clears the twenty percent floor of 5000, so the down-payment rule
    # cannot fire ahead of the amount match.
    validate_error(
        api.create_payment_arrangement(
            factories.payment_arrangement_payload(
                ctx["account_id"], ctx["bill_id"], 5000, 1042, 4, token
            ),
            CSR_HEADERS,
        ),
        "ERR_ARRANGEMENT_AMOUNT_MISMATCH",
    )

    assert (
        _total_count(
            api.list_payment_arrangements(
                CSR_HEADERS, {"account_id": ctx["account_id"], "limit": 100}
            )
        )
        == 0
    )


def test_refused_proposals_leave_the_account_version_token_spendable(api):
    """PRD §2.6: "Proposing a payment arrangement requires `expected_account_version` as a non-optional field of the request payload, carrying the client's last observed `version` of the parent `ServiceAccount`."

    PRD §3.8: "`installment_cents` is the financed amount divided by `installment_count`, taking the floor — the largest whole number of cents not exceeding the quotient — and it applies to every instalment from the first through the second-to-last."

    Design: Corner/errors/corner_error_payment_arrangement_fiscal_and_referential_guards_all_fire
    """
    ctx = _two_billed_accounts(api)
    token = fixtures.account_version(api, ctx["account_id"])

    refusals = [
        (
            factories.payment_arrangement_payload(
                ctx["account_id"], ctx["bill_id"], 5210, 1041, 4, token
            ),
            "ERR_DOWN_PAYMENT_TOO_LOW",
        ),
        (
            factories.payment_arrangement_payload(
                ctx["account_id"], ctx["bill_id"], 5210, 1042, 13, token
            ),
            "ERR_INSTALLMENT_LIMIT_EXCEEDED",
        ),
        (
            factories.payment_arrangement_payload(
                ctx["account_id"], ctx["other_bill_id"], 5210, 1042, 4, token
            ),
            "ERR_ARRANGEMENT_ACCOUNT_MISMATCH",
        ),
        (
            factories.payment_arrangement_payload(
                ctx["account_id"], ctx["bill_id"], 5000, 1042, 4, token
            ),
            "ERR_ARRANGEMENT_AMOUNT_MISMATCH",
        ),
    ]
    for payload, expected_error_id in refusals:
        validate_error(
            api.create_payment_arrangement(payload, CSR_HEADERS), expected_error_id
        )

    arrangement = validate_success(
        api.create_payment_arrangement(
            factories.payment_arrangement_payload(
                ctx["account_id"], ctx["bill_id"], 5210, 1042, 4, token
            ),
            CSR_HEADERS,
        ),
        201,
    )
    assertions.assert_fields(
        arrangement,
        status="PROPOSED",
        total_amount_cents=5210,
        down_payment_cents=1042,
        installment_count=4,
        installment_cents=1042,
        final_installment_cents=1042,
        paid_installment_count=0,
        missed_payment_count=0,
        reinstatement_count=0,
    )
    assertions.assert_account_state(
        fixtures.fetch_account(api, ctx["account_id"]), balance_cents=5210
    )


# ===========================================================================
# Meter-test intake and the half-open result window
# ===========================================================================


def test_meter_test_request_naming_a_foreign_meter_is_refused(api):
    """PRD §3.4: "The tested meter must belong to the same account as the investigation, else `ERR_TEST_METER_ACCOUNT_MISMATCH`."

    Design: Corner/errors/corner_error_meter_test_intake_deposit_meter_scope_and_result_window_guards
    """
    ctx = _investigation_test_estate(api)

    # The deposit declared here is the correct one for a CUSTOMER request, so
    # only the meter reference can be at fault.
    validate_error(
        api.create_meter_test_request(
            factories.meter_test_request_payload(
                ctx["investigation_id"], ctx["other_meter_id"], "FIELD", "CUSTOMER"
            ),
            CSR_HEADERS,
        ),
        "ERR_TEST_METER_ACCOUNT_MISMATCH",
    )

    assert (
        _total_count(
            api.list_meter_test_requests(
                CSR_HEADERS,
                {"investigation_id": ctx["investigation_id"], "limit": 100},
            )
        )
        == 0
    )
    entries = assertions.ledger_entries(api, ctx["account_id"], CSR_HEADERS)
    assertions.assert_no_entry_of_kind(entries, "METER_TEST_DEPOSIT")
    assertions.assert_account_state(
        fixtures.fetch_account(api, ctx["account_id"]), balance_cents=60569
    )


def test_the_deposit_must_match_the_declared_paying_party_exactly(api):
    """PRD §3.4: "Who pays is supplied in the payload rather than inferred from the caller's role, so a representative or a technician may file either kind on the customer's behalf — but the money must match the declaration exactly: a `CUSTOMER`-funded test requires `deposit_cents` of exactly 3,000 cents (thirty dollars) and a `UTILITY`-funded test requires exactly 0, and any other combination is refused with `ERR_TEST_DEPOSIT_INVALID`."

    Design: Corner/errors/corner_error_meter_test_intake_deposit_meter_scope_and_result_window_guards
    """
    ctx = _investigation_test_estate(api)

    validate_error(
        api.create_meter_test_request(
            factories.meter_test_request_payload(
                ctx["investigation_id"],
                ctx["meter_id"],
                "FIELD",
                "CUSTOMER",
                deposit_cents=0,
            ),
            CSR_HEADERS,
        ),
        "ERR_TEST_DEPOSIT_INVALID",
    )
    # The very amount that was mandatory a moment ago is now forbidden.
    validate_error(
        api.create_meter_test_request(
            factories.meter_test_request_payload(
                ctx["investigation_id"],
                ctx["meter_id"],
                "FIELD",
                "UTILITY",
                deposit_cents=3000,
            ),
            CSR_HEADERS,
        ),
        "ERR_TEST_DEPOSIT_INVALID",
    )

    assert (
        _total_count(
            api.list_meter_test_requests(
                CSR_HEADERS,
                {"investigation_id": ctx["investigation_id"], "limit": 100},
            )
        )
        == 0
    )
    entries = assertions.ledger_entries(api, ctx["account_id"], CSR_HEADERS)
    assert len(entries) == 4
    assertions.assert_no_entry_of_kind(entries, "METER_TEST_DEPOSIT")


def test_field_result_at_the_excluded_window_end_is_refused(api):
    """PRD §3.4: "The `tested_at` instant must fall inside the reserved half-open window — at or after `window_start` and strictly before `window_end` — else `ERR_TEST_RESULT_OUTSIDE_WINDOW`."

    Design: Corner/errors/corner_error_meter_test_intake_deposit_meter_scope_and_result_window_guards
    """
    ctx = _investigation_test_estate(api)
    request = fixtures.request_meter_test(
        api, ctx["investigation_id"], ctx["meter_id"], "FIELD", "CUSTOMER", CSR_HEADERS
    )
    scheduled = fixtures.schedule_field_test(
        api, request["id"], "2026-08-05T09:00:00Z", "2026-08-05T12:00:00Z"
    )
    assertions.assert_fields(scheduled, status="FIELD_TEST_SCHEDULED")
    fixtures.set_clock(api, "2026-08-06T00:00:00Z")

    validate_error(
        api.record_field_result(
            request["id"],
            factories.field_result_payload("PASS", "2026-08-05T12:00:00Z"),
            TECHNICIAN_HEADERS,
        ),
        "ERR_TEST_RESULT_OUTSIDE_WINDOW",
    )

    after = validate_success(
        api.get_meter_test_request(request["id"], TECHNICIAN_HEADERS)
    )
    assertions.assert_fields(after, status="FIELD_TEST_SCHEDULED")
    assertions.assert_null_fields(after, "tested_at", "field_result")
    assertions.assert_fields(
        fixtures.fetch_meter(api, ctx["meter_id"]), accuracy_status="UNTESTED"
    )
    assertions.assert_account_state(
        fixtures.fetch_account(api, ctx["account_id"]), balance_cents=63569
    )


def test_field_result_at_the_included_window_start_closes_the_request(api):
    """PRD §3.4: "`PASS` closes the request at `CLOSED_PASS`, sets the meter's `accuracy_status` to `VERIFIED_ACCURATE` and its `last_test_completed_at` to `tested_at`, forfeits the deposit — no refund entry is written and `deposit_refunded` stays false, because the customer's suspicion was unfounded — and advances the investigation from `EVIDENCE_REQUESTED` to `EVIDENCE_UNDER_REVIEW`."

    Design: Corner/errors/corner_error_meter_test_intake_deposit_meter_scope_and_result_window_guards
    """
    ctx = _investigation_test_estate(api)
    request = fixtures.request_meter_test(
        api, ctx["investigation_id"], ctx["meter_id"], "FIELD", "CUSTOMER", CSR_HEADERS
    )
    assertions.assert_fields(request, status="REQUESTED", deposit_refunded=False)
    assertions.assert_null_fields(request, "window_start", "window_end")
    fixtures.schedule_field_test(
        api, request["id"], "2026-08-05T09:00:00Z", "2026-08-05T12:00:00Z"
    )
    fixtures.set_clock(api, "2026-08-06T00:00:00Z")

    closed = validate_success(
        api.record_field_result(
            request["id"],
            factories.field_result_payload("PASS", "2026-08-05T09:00:00Z"),
            TECHNICIAN_HEADERS,
        )
    )
    assertions.assert_fields(
        closed, status="CLOSED_PASS", field_result="PASS", deposit_refunded=False
    )
    assert closed["tested_at"].startswith("2026-08-05T09:00:00")

    meter = fixtures.fetch_meter(api, ctx["meter_id"])
    assertions.assert_fields(meter, accuracy_status="VERIFIED_ACCURATE")
    assert meter["last_test_completed_at"].startswith("2026-08-05T09:00:00")

    entries = assertions.ledger_entries(api, ctx["account_id"], CSR_HEADERS)
    assertions.assert_single_entry(entries, "METER_TEST_DEPOSIT", amount_cents=3000)
    assertions.assert_no_entry_of_kind(entries, "METER_TEST_DEPOSIT_REFUND")
    assertions.assert_account_state(
        fixtures.fetch_account(api, ctx["account_id"]),
        balance_cents=63569,
        credit_status="PAST_DUE",
    )
    # The escalation is defined out of EVIDENCE_REQUESTED only, and no evidence
    # round was ever opened on this case.
    assertions.assert_fields(
        fixtures.fetch_investigation(api, ctx["investigation_id"]), status="OPEN"
    )


# ===========================================================================
# Board hearings: notice, timing, the officer bar and the remand ceiling
# ===========================================================================


def test_hearing_docketed_one_day_short_of_the_notice_is_refused(api):
    """PRD §3.9: "The customer is entitled to notice, so `hearing_date` must be at or after the appeal's `filing_date` plus ten calendar days, else `ERR_HEARING_NOTICE_TOO_SHORT`."

    Design: Corner/errors/corner_error_board_hearing_notice_timing_officer_and_remand_guards
    """
    ctx = _closed_case_under_appeal(api)
    assert ctx["appeal"]["filing_date"].startswith("2026-08-01")

    validate_error(
        api.schedule_hearing(
            ctx["appeal_id"],
            factories.hearing_schedule_payload("2026-08-10"),
            CLERK_HEADERS,
        ),
        "ERR_HEARING_NOTICE_TOO_SHORT",
    )
    refused = fixtures.fetch_appeal(api, ctx["appeal_id"])
    assertions.assert_fields(refused, status="FILED")
    assertions.assert_null_fields(refused, "hearing_date")

    # Exactly ten days is inside the notice period.
    docketed = validate_success(
        api.schedule_hearing(
            ctx["appeal_id"],
            factories.hearing_schedule_payload("2026-08-11"),
            CLERK_HEADERS,
        )
    )
    assertions.assert_fields(
        docketed, status="SCHEDULED", hearing_date="2026-08-11"
    )


def test_decision_recorded_before_the_hearing_date_is_refused(api):
    """PRD §3.9: "Today's date on the logical clock must be at or after `hearing_date`, else `ERR_HEARING_NOT_YET_HELD`."

    Design: Corner/errors/corner_error_board_hearing_notice_timing_officer_and_remand_guards
    """
    ctx = _closed_case_under_appeal(api)
    fixtures.schedule_hearing(api, ctx["appeal_id"], "2026-08-11")

    validate_error(
        api.record_board_decision(
            ctx["appeal_id"],
            factories.board_decision_payload("REMAND"),
            CLERK_HEADERS,
        ),
        "ERR_HEARING_NOT_YET_HELD",
    )

    after = fixtures.fetch_appeal(api, ctx["appeal_id"])
    assertions.assert_fields(after, status="SCHEDULED")
    assertions.assert_null_fields(
        after, "decision", "decision_note", "hearing_officer_user_id"
    )
    assertions.assert_fields(
        fixtures.fetch_investigation(api, ctx["investigation_id"]),
        status="APPEALED",
        remand_count=0,
    )


def test_the_filer_may_not_sit_as_the_hearing_officer(api):
    """PRD §3.9: "The acting `X-User-ID` must differ both from the investigation's `determination_by_user_id` and from the appeal's own `filed_by_user_id`, else `ERR_HEARING_OFFICER_CONFLICT`."

    PRD §2.1: "Recording a board decision fails with `ERR_HEARING_OFFICER_CONFLICT` when the acting `X-User-ID` equals either that same `determination_by_user_id` or the appeal's `filed_by_user_id`."

    Design: Corner/errors/corner_error_board_hearing_notice_timing_officer_and_remand_guards
    """
    ctx = _closed_case_under_appeal(api)
    fixtures.schedule_hearing(api, ctx["appeal_id"], "2026-08-11")
    fixtures.set_clock(api, "2026-08-11T15:00:00Z")

    # The clerk role is held, and the hearing day has arrived, so only the
    # identifier comparison can refuse this call.
    validate_error(
        api.record_board_decision(
            ctx["appeal_id"],
            factories.board_decision_payload("REMAND"),
            make_clerk_headers("u-shared"),
        ),
        "ERR_HEARING_OFFICER_CONFLICT",
    )

    after = fixtures.fetch_appeal(api, ctx["appeal_id"])
    assertions.assert_fields(after, status="SCHEDULED")
    assertions.assert_null_fields(after, "decision", "hearing_officer_user_id")
    assertions.assert_fields(
        fixtures.fetch_investigation(api, ctx["investigation_id"]),
        status="APPEALED",
        remand_count=0,
    )


def test_second_remand_is_refused_while_upholding_the_same_hearing_still_works(api):
    """PRD §3.9: "Only one remand is ever absorbed per investigation: an attempt made when `remand_count` has already reached one is refused with `ERR_REMAND_LIMIT_EXCEEDED`."

    PRD §3.9: "`UPHOLD` moves the appeal to the terminal `UPHELD`, moves the investigation from `APPEALED` to `RESOLVED` with `shutoff_hold_active` becoming false, settles the bill from `UNDER_INVESTIGATION` to `UPHELD_AS_BILLED`, and writes no ledger entry at all."

    Design: Corner/errors/corner_error_board_hearing_notice_timing_officer_and_remand_guards
    """
    ctx = _remanded_case_on_a_second_appeal(api)

    validate_error(
        api.record_board_decision(
            ctx["second_appeal_id"],
            factories.board_decision_payload("REMAND"),
            CLERK_HEADERS,
        ),
        "ERR_REMAND_LIMIT_EXCEEDED",
    )
    refused = fixtures.fetch_appeal(api, ctx["second_appeal_id"])
    assertions.assert_fields(refused, status="SCHEDULED")
    assertions.assert_null_fields(refused, "decision")
    assertions.assert_fields(
        fixtures.fetch_investigation(api, ctx["investigation_id"]),
        status="APPEALED",
        remand_count=1,
    )

    upheld = validate_success(
        api.record_board_decision(
            ctx["second_appeal_id"],
            factories.board_decision_payload("UPHOLD"),
            CLERK_HEADERS,
        )
    )
    assertions.assert_fields(
        upheld, status="UPHELD", decision="UPHOLD", hearing_officer_user_id="clerk-1"
    )
    assertions.assert_fields(
        fixtures.fetch_investigation(api, ctx["investigation_id"]),
        status="RESOLVED",
        shutoff_hold_active=False,
        remand_count=1,
    )
    assertions.assert_fields(
        fixtures.fetch_bill(api, ctx["bill_id"]), billing_status="UPHELD_AS_BILLED"
    )
    entries = assertions.ledger_entries(api, ctx["account_id"], CSR_HEADERS)
    assertions.assert_source_kinds(
        entries, ["BILL_CHARGE", "BILL_CHARGE", "BILL_CHARGE", "BILL_CHARGE"]
    )
    assertions.assert_account_state(
        fixtures.fetch_account(api, ctx["account_id"]),
        balance_cents=60569,
        open_investigation_hold_count=0,
    )


# ===========================================================================
# Investigation intake: one code, two clauses
# ===========================================================================


def test_second_investigation_on_a_live_case_is_refused(api):
    """PRD §3.3: "No non-terminal investigation may already exist for that bill, else `ERR_INVESTIGATION_ALREADY_OPEN`."

    Design: Corner/errors/corner_error_investigation_intake_refuses_both_the_open_case_and_the_settled_bill
    """
    ctx = fixtures.investigation_case(api, request_first_round=False)

    validate_error(
        api.create_investigation(
            factories.investigation_payload(
                ctx["bill_id"], reported_cause="a second case on the same bill"
            ),
            CSR_HEADERS,
        ),
        "ERR_INVESTIGATION_ALREADY_OPEN",
    )

    assert (
        _total_count(
            api.list_investigations(
                CSR_HEADERS, {"bill_id": ctx["bill_id"], "limit": 100}
            )
        )
        == 1
    )
    assertions.assert_fields(
        fixtures.fetch_investigation(api, ctx["investigation_id"]), status="OPEN"
    )
    assertions.assert_fields(
        fixtures.fetch_bill(api, ctx["bill_id"]), billing_status="UNDER_INVESTIGATION"
    )


def test_investigation_on_a_settled_bill_carries_the_same_refusal_code(api):
    """PRD §2.7: "Two state checks carry their own codes: opening an investigation requires the target bill to be `ISSUED` and requires that no non-terminal investigation already exists for it, else `ERR_INVESTIGATION_ALREADY_OPEN` (409); generating a bill requires its period to be `OPEN`, else `ERR_BILLING_PERIOD_CLOSED` (409)."

    PRD §3.3: "Closing without a credit is available from `OPEN`, `EVIDENCE_REQUESTED`, `EVIDENCE_UNDER_REVIEW` and `EVIDENCE_EXHAUSTED`, takes an optional `note`, and lands the investigation in `CLOSED_NO_ADJUSTMENT`."

    Design: Corner/errors/corner_error_investigation_intake_refuses_both_the_open_case_and_the_settled_bill
    """
    ctx = fixtures.investigation_case(api, request_first_round=False)
    closed = validate_success(
        api.close_investigation_no_adjustment(
            ctx["investigation_id"],
            CSR_HEADERS,
            factories.close_no_adjustment_payload(),
        )
    )
    assertions.assert_fields(closed, status="CLOSED_NO_ADJUSTMENT")
    assertions.assert_fields(
        fixtures.fetch_bill(api, ctx["bill_id"]), billing_status="UPHELD_AS_BILLED"
    )

    # The existing case is terminal now, so this refusal can only come from the
    # other clause of the same rule: the bill has left ISSUED.
    validate_error(
        api.create_investigation(
            factories.investigation_payload(
                ctx["bill_id"], reported_cause="a third attempt after the case closed"
            ),
            CSR_HEADERS,
        ),
        "ERR_INVESTIGATION_ALREADY_OPEN",
    )

    assert (
        _total_count(
            api.list_investigations(
                CSR_HEADERS, {"bill_id": ctx["bill_id"], "limit": 100}
            )
        )
        == 1
    )
    assertions.assert_account_state(
        fixtures.fetch_account(api, ctx["account_id"]),
        open_investigation_hold_count=0,
        balance_cents=60569,
    )
    assertions.assert_fields(
        fixtures.fetch_bill(api, ctx["bill_id"]), billing_status="UPHELD_AS_BILLED"
    )
