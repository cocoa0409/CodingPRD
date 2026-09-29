"""Queue B — Corner design index, section: validations.

One test per non-stub `validations` instance of SCAFFOLD_CORNER_DESIGN.yaml: the
masked-error orderings of the §2.11 ladder plus the inclusive/exclusive edges of
individual guards. Every test carries exactly one design tag naming the instance
it translates.
"""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.assertions import assert_money_equals
from test_helpers.test_users import (
    headers_for_role,
    make_adjuster_headers,
    make_catastrophe_manager_headers,
    make_claims_examiner_headers,
    make_compliance_officer_headers,
    make_deployment_coordinator_headers,
    make_vendor_coordinator_headers,
)

CM = make_catastrophe_manager_headers("cm_1")
DC = make_deployment_coordinator_headers("dc_1")
CE = make_claims_examiner_headers("ce_1")
CE_OTHER = make_claims_examiner_headers("ce_2")
CO = make_compliance_officer_headers("co_1")


def _declared_event(api, cat_code, **overrides):
    """A DECLARED HURRICANE/FL event at expected_severity_index 0.0400."""
    payload = {
        "cat_code": cat_code,
        "peril_type": "HURRICANE",
        "jurisdiction_state": "FL",
        "event_start_utc": "2026-07-30T00:00:00.000Z",
        "exposure_count": 1000,
        "avg_insured_value": 250000,
        "expected_severity_index": 0.0400,
    }
    payload.update(overrides)
    event = validate_success(api.create_event(payload, CM), 201)
    return validate_success(api.declare_event(event["id"], CM))


def _dwelling_claim(api, event_id, policy_number, **overrides):
    """An INTAKE claim with a single ACCESSIBLE DWELLING coverage line, whose
    triage lands on STANDARD / FIELD with a 65250.00 initial case reserve."""
    payload = {
        "policy_number": policy_number,
        "loss_state": "FL",
        "loss_date_utc": "2026-07-30T00:00:00.000Z",
        "reported_loss_amount": 120000,
        "coverage_lines": [
            {
                "coverage_code": "DWELLING",
                "limit_amount": 400000,
                "deductible_amount": 5000,
                "estimated_damage_amount": 150000,
            }
        ],
        "event_id": event_id,
        "access_status": "ACCESSIBLE",
    }
    payload.update(overrides)
    return validate_success(api.create_claim(payload, CE), 201)


def _staff_adjuster(api, full_name, **overrides):
    """A registered STAFF adjuster licensed in FL with a long-dated licence."""
    payload = {
        "full_name": full_name,
        "employment_type": "STAFF",
        "home_state": "FL",
        "licensed_states": ["FL"],
        "license_expiry_utc": "2027-06-30T00:00:00.000Z",
        "max_open_claims": 5,
        "daily_rate": 900,
        "per_diem_rate": 150,
        "desk_certified": False,
        "aerial_certified": False,
    }
    payload.update(overrides)
    return validate_success(api.create_adjuster(payload, DC), 201)


# ---------------------------------------------------------------------------
# Instance — corner_val_role_not_permitted_precedes_body_schema_check
# ---------------------------------------------------------------------------
def test_role_permission_is_checked_before_the_body_schema(api):
    """PRD §2.11: "The response always carries the error belonging to the
    **lowest-numbered** rule in the ladder below; evaluation stops at the first
    failure, so a later, more interesting violation is masked by an earlier one."
    PRD §2.11: "Positions 1 through 3 are authentication and authorisation: header
    presence (`ERR_MISSING_AUTH_HEADERS`), role recognition (`ERR_UNKNOWN_ROLE`),
    then endpoint permission (`ERR_ROLE_NOT_PERMITTED`)."
    PRD §2.11: "Position 15 is request-schema validation, covering required fields,
    type correctness, enum membership and numeric ranges: `rooms_total` from 0
    through 400, `max_open_claims` from 1 through 60, `expected_severity_index`
    from 0.0 through 1.0, `mandated_advance_pct` from 0.0 through 1.0,
    `deadline_extension_days` from 0 through 365, `coverage_lines` holding 1
    through 6 entries with no repeated coverage code, `performance_score` from 0
    through 100, and `limit` and `offset` within their pagination bounds; the
    failure is `ERR_VALIDATION` (HTTP 422)."

    Design: Corner/validations/corner_val_role_not_permitted_precedes_body_schema_check
    """
    response = api.create_event(
        {
            "cat_code": "CAT-2026-301",
            "peril_type": "HURRICANE",
            "jurisdiction_state": "FL",
            "event_start_utc": "2026-07-30T00:00:00.000Z",
            "exposure_count": 1000,
            "avg_insured_value": 250000,
            "expected_severity_index": 5.0,
        },
        DC,
    )

    error = validate_error(response, ApiErrorId.ERR_ROLE_NOT_PERMITTED, 403)
    assert error["error_id"] != ApiErrorId.ERR_VALIDATION.value

    _, meta = validate_paginated(api.list_events(DC))
    assert meta["total_count"] == 0


# ---------------------------------------------------------------------------
# Instance — corner_val_unknown_role_precedes_event_existence_lookup
# ---------------------------------------------------------------------------
def test_unknown_role_is_rejected_before_the_event_is_looked_up(api):
    """PRD §2.11: "Positions 1 through 3 are authentication and authorisation:
    header presence (`ERR_MISSING_AUTH_HEADERS`), role recognition
    (`ERR_UNKNOWN_ROLE`), then endpoint permission (`ERR_ROLE_NOT_PERMITTED`)."
    PRD §2.11: "Positions 4 through 14 are existence checks in a fixed entity
    order — event, claim, adjuster, housing block, deployment, inspection
    assignment, advance payment, vendor firm, vendor assignment, regulatory
    bulletin, file-transfer batch — each producing its own not-found error."
    PRD §2.11: "The response always carries the error belonging to the
    **lowest-numbered** rule in the ladder below; evaluation stops at the first
    failure, so a later, more interesting violation is masked by an earlier one."

    Design: Corner/validations/corner_val_unknown_role_precedes_event_existence_lookup
    """
    response = api.get_event(NON_EXISTENT_UUID, headers_for_role("SurgeIntern", "intern_1"))

    error = validate_error(response, ApiErrorId.ERR_UNKNOWN_ROLE, 401)
    assert error["error_id"] != ApiErrorId.ERR_EVENT_NOT_FOUND.value


# ---------------------------------------------------------------------------
# Instance — corner_val_claim_existence_precedes_occ_version_check
# ---------------------------------------------------------------------------
def test_claim_existence_is_checked_before_the_version_token(api):
    """PRD §2.11: "Positions 4 through 14 are existence checks in a fixed entity
    order — event, claim, adjuster, housing block, deployment, inspection
    assignment, advance payment, vendor firm, vendor assignment, regulatory
    bulletin, file-transfer batch — each producing its own not-found error."
    PRD §2.11: "Position 18 is the optimistic-concurrency check described in §2.8,
    on the two endpoints that carry a version field."
    PRD §2.8: "A request that appends a manual reserve entry to a claim must carry
    `expected_claim_version` holding the client's last observed `version` of that
    `Claim`."

    Design: Corner/validations/corner_val_claim_existence_precedes_occ_version_check
    """
    event = _declared_event(api, "CAT-2026-302")
    claim = _dwelling_claim(api, event["id"], "POL-302")

    response = api.create_reserve_entry(
        NON_EXISTENT_UUID,
        {
            "entry_type": "REVISION",
            "delta_case_reserve": 100.00,
            "delta_paid": 0,
            "expected_claim_version": claim["version"],
        },
        CE,
    )

    error = validate_error(response, ApiErrorId.ERR_CLAIM_NOT_FOUND, 404)
    assert error["error_id"] != ApiErrorId.ERR_STALE_CLAIM_VERSION.value

    _, meta = validate_paginated(api.list_reserve_entries(CE, params={"claim_id": claim["id"]}))
    assert meta["total_count"] == 0


# ---------------------------------------------------------------------------
# Instance — corner_val_stale_claim_version_precedes_negative_reserve_check
# ---------------------------------------------------------------------------
def test_stale_claim_version_masks_the_negative_reserve_guard(api):
    """PRD §2.11: "Position 18 is the optimistic-concurrency check described in
    §2.8, on the two endpoints that carry a version field."
    PRD §2.11: "Positions 38 through 41 are the fiscal rules — housing room
    availability at confirm, advance headroom, the advance mandate floor on void,
    and the non-negative case-reserve rule on manual entries."
    PRD §2.8: "If that value does not equal the claim's current `version`, the
    request is rejected with `ERR_STALE_CLAIM_VERSION` (HTTP 412) and no ledger row
    is written."
    PRD §3.8: "One fiscal guard applies: the claim's `case_reserve` plus the
    submitted `delta_case_reserve`, rounded to 2 decimal places, must be at least
    0.00, otherwise the append is refused with `ERR_RESERVE_WOULD_GO_NEGATIVE`
    (HTTP 422)."

    Design: Corner/validations/corner_val_stale_claim_version_precedes_negative_reserve_check
    """
    event = _declared_event(api, "CAT-2026-303")
    claim = _dwelling_claim(api, event["id"], "POL-303")
    pre_triage_version = claim["version"]
    triaged = validate_success(api.triage_claim(claim["id"], CE))
    assert triaged["version"] != pre_triage_version

    response = api.create_reserve_entry(
        claim["id"],
        {
            "entry_type": "REVISION",
            "delta_case_reserve": -999999.00,
            "delta_paid": 0,
            "expected_claim_version": pre_triage_version,
        },
        CE,
    )

    error = validate_error(response, ApiErrorId.ERR_STALE_CLAIM_VERSION, 412)
    assert error["error_id"] != ApiErrorId.ERR_RESERVE_WOULD_GO_NEGATIVE.value

    refreshed = validate_success(api.get_claim(claim["id"], CE))
    assert_money_equals(refreshed["case_reserve"], 65250.00, "case_reserve")
    _, meta = validate_paginated(api.list_reserve_entries(CE, params={"claim_id": claim["id"]}))
    assert meta["total_count"] == 1


# ---------------------------------------------------------------------------
# Instance — corner_val_assignment_exact_adjacency_accepted_zero_buffer
# ---------------------------------------------------------------------------
def test_exactly_adjacent_inspection_windows_are_accepted(api):
    """PRD §3.7: "The window must not clash with the adjuster's other live
    inspection work: under **strict half-open, zero-buffer** semantics, a conflict
    exists when the new window's start is earlier than another `SCHEDULED` or
    `IN_PROGRESS` assignment's end *and* that assignment's start is earlier than
    the new window's end."
    PRD §3.7: "Because the buffer is zero, exact adjacency is **accepted** — an
    assignment starting at the precise instant another ends is legal, in deliberate
    contrast to the twelve-hour rest buffer that governs deployments — and a
    genuine overlap is `ERR_ASSIGNMENT_WINDOW_CONFLICT`."
    PRD §3.7: "Creation also pulls the claim onto the inspection track: a claim in
    `TRIAGED` moves `TRIAGED → INSPECTION_PENDING`, and a claim in `REOPENED` moves
    `REOPENED → INSPECTION_PENDING`; both branches are driven by the same event — an
    assignment for the claim coming into existence in `SCHEDULED` — and both leave
    no further side effects of their own."
    PRD §3.3: "The **availability term** starts from the adjuster's
    `open_assignment_count` — the number of their inspection assignments currently
    in `SCHEDULED` or `IN_PROGRESS` — divided by their `max_open_claims`; that load
    ratio is capped at 1, subtracted from 1, and multiplied by 100, so an idle
    adjuster contributes 100 points and a fully loaded one contributes zero."

    Design: Corner/validations/corner_val_assignment_exact_adjacency_accepted_zero_buffer
    """
    event = _declared_event(api, "CAT-2026-304")
    adjuster = _staff_adjuster(api, "Abe Adjacent")
    claim_a = _dwelling_claim(api, event["id"], "POL-304-A")
    validate_success(api.triage_claim(claim_a["id"], CE))
    claim_b = _dwelling_claim(api, event["id"], "POL-304-B")
    validate_success(api.triage_claim(claim_b["id"], CE))

    validate_success(
        api.create_inspection_assignment(
            {
                "claim_id": claim_a["id"],
                "mode": "FIELD",
                "window_start_utc": "2026-08-10T08:00:00.000Z",
                "window_end_utc": "2026-08-10T12:00:00.000Z",
                "adjuster_id": adjuster["id"],
            },
            DC,
        ),
        201,
    )

    second = validate_success(
        api.create_inspection_assignment(
            {
                "claim_id": claim_b["id"],
                "mode": "FIELD",
                "window_start_utc": "2026-08-10T12:00:00.000Z",
                "window_end_utc": "2026-08-10T16:00:00.000Z",
                "adjuster_id": adjuster["id"],
            },
            DC,
        ),
        201,
    )

    # The second window starts at the precise instant the first ends.
    assert second["status"] == "SCHEDULED"
    refreshed_adjuster = validate_success(api.get_adjuster(adjuster["id"], DC))
    assert refreshed_adjuster["open_assignment_count"] == 2
    # (1 - 2/5) * 100 = 60.00, with no credential or fatigue penalty.
    assert_money_equals(refreshed_adjuster["surge_capacity_score"], 60.00, "surge_capacity_score")
    refreshed_claim_b = validate_success(api.get_claim(claim_b["id"], CE))
    assert refreshed_claim_b["handling_status"] == "INSPECTION_PENDING"


# ---------------------------------------------------------------------------
# Instance — corner_val_waived_credential_satisfies_state_licensing_check
# ---------------------------------------------------------------------------
def test_a_waived_credential_satisfies_the_state_licensing_check(api):
    """PRD §3.7: "The event's `jurisdiction_state` must appear in the chosen
    adjuster's `licensed_states` unless their `credential_status` is `WAIVED`
    (`ERR_ADJUSTER_NOT_LICENSED_IN_STATE`)."
    PRD §3.3: "An expired independent adjuster can be rescued: a
    `ComplianceOfficer` applies an emergency licence waiver, naming the `event_id`
    whose regulator issued the waiver, which moves the adjuster `EXPIRED → WAIVED`
    and recomputes the score with an 8-point credential penalty."
    PRD §3.3: "From that, the **credential penalty** for the adjuster's current
    `credential_status` is subtracted: zero points for `VALID`, 15 points for
    `EXPIRING`, 8 points for `WAIVED`, and 100 points for `EXPIRED`."
    PRD §2.6: "Bulletins whose binding window has ended move from `EFFECTIVE` to
    `EXPIRED`; adjusters whose licence enters its warning window move from `VALID`
    to `EXPIRING`, and from `EXPIRING` to `EXPIRED` once the licence lapses;
    adjusters whose rest buffer has elapsed move from `RESTING` back to
    `AVAILABLE`; and adjusters sustained only by a licence waiver that has stopped
    covering the current instant fall from `WAIVED` back to `EXPIRED`."

    Design: Corner/validations/corner_val_waived_credential_satisfies_state_licensing_check
    """
    event = _declared_event(api, "CAT-2026-305")
    waiver = validate_success(
        api.create_bulletin(
            {
                "event_id": event["id"],
                "bulletin_number": "FL-2026-W1",
                "bulletin_type": "ADJUSTER_LICENSE_WAIVER",
                "jurisdiction_state": "FL",
                "effective_from": "2026-08-01T00:00:00.000Z",
                "effective_to": "2026-12-01T00:00:00.000Z",
            },
            CO,
        ),
        201,
    )
    validate_success(api.activate_bulletin(waiver["id"], CO))
    adjuster = _staff_adjuster(
        api,
        "Gia Georgia",
        employment_type="INDEPENDENT",
        home_state="GA",
        licensed_states=["GA"],
        license_expiry_utc="2026-08-10T00:00:00.000Z",
    )
    claim = _dwelling_claim(api, event["id"], "POL-305")
    validate_success(api.triage_claim(claim["id"], CE))
    validate_success(api.set_clock("2026-08-11T00:00:00.000Z", CM))

    waived = validate_success(api.apply_license_waiver(adjuster["id"], {"event_id": event["id"]}, CO))
    assert waived["credential_status"] == "WAIVED"

    assignment = validate_success(
        api.create_inspection_assignment(
            {
                "claim_id": claim["id"],
                "mode": "FIELD",
                "window_start_utc": "2026-08-12T08:00:00.000Z",
                "window_end_utc": "2026-08-12T12:00:00.000Z",
                "adjuster_id": adjuster["id"],
            },
            DC,
        ),
        201,
    )

    # FL is absent from the adjuster's licensed_states; the waiver stands in.
    assert assignment["status"] == "SCHEDULED"
    refreshed_adjuster = validate_success(api.get_adjuster(adjuster["id"], DC))
    assert refreshed_adjuster["credential_status"] == "WAIVED"
    assert refreshed_adjuster["open_assignment_count"] == 1
    # (1 - 1/5) * 100 = 80, less the 8-point WAIVED penalty.
    assert_money_equals(refreshed_adjuster["surge_capacity_score"], 72.00, "surge_capacity_score")
    refreshed_claim = validate_success(api.get_claim(claim["id"], CE))
    assert refreshed_claim["handling_status"] == "INSPECTION_PENDING"


# ---------------------------------------------------------------------------
# Instance — corner_val_event_scope_mismatch_when_deployment_belongs_to_other_event
# ---------------------------------------------------------------------------
def test_funding_deployment_from_another_event_is_a_scope_mismatch(api):
    """PRD §3.7: "And the funding deployment must belong to the same event as the
    claim, otherwise `ERR_EVENT_SCOPE_MISMATCH`."
    PRD §3.7: "When a funding deployment is named, the assignment window must be
    fully **contained** in it: the deployment's `window_start_utc` must be at or
    before the assignment's `window_start_utc`, and the assignment's
    `window_end_utc` must be at or before the deployment's `window_end_utc`,
    otherwise `ERR_ASSIGNMENT_OUTSIDE_DEPLOYMENT` (HTTP 422)."
    PRD §2.11: "Positions 27 through 30 are referential rules — adjuster state
    licensing, vendor state licensing, inspection-mode agreement, and
    cross-aggregate event scope."

    Design: Corner/validations/corner_val_event_scope_mismatch_when_deployment_belongs_to_other_event
    """
    event_a = _declared_event(api, "CAT-2026-306")
    event_b = _declared_event(api, "CAT-2026-307")
    adjuster = _staff_adjuster(api, "Sam Scope")
    claim = _dwelling_claim(api, event_a["id"], "POL-306")
    validate_success(api.triage_claim(claim["id"], CE))
    deployment_b = validate_success(
        api.create_deployment(
            {
                "event_id": event_b["id"],
                "role_type": "FIELD",
                "window_start_utc": "2026-08-10T00:00:00.000Z",
                "window_end_utc": "2026-08-14T00:00:00.000Z",
                "adjuster_id": adjuster["id"],
                "rooms_reserved": 1,
            },
            DC,
        ),
        201,
    )

    response = api.create_inspection_assignment(
        {
            "claim_id": claim["id"],
            "mode": "FIELD",
            "window_start_utc": "2026-08-11T08:00:00.000Z",
            "window_end_utc": "2026-08-11T12:00:00.000Z",
            "adjuster_id": adjuster["id"],
            "deployment_id": deployment_b["id"],
        },
        DC,
    )

    # The window is fully contained in the deployment, so only the scope rule bites.
    error = validate_error(response, ApiErrorId.ERR_EVENT_SCOPE_MISMATCH, 409)
    assert error["error_id"] != ApiErrorId.ERR_ASSIGNMENT_OUTSIDE_DEPLOYMENT.value

    refreshed_claim = validate_success(api.get_claim(claim["id"], CE))
    assert refreshed_claim["handling_status"] == "TRIAGED"
    _, meta = validate_paginated(
        api.list_inspection_assignments(DC, params={"claim_id": claim["id"]})
    )
    assert meta["total_count"] == 0
    refreshed_adjuster = validate_success(api.get_adjuster(adjuster["id"], DC))
    assert refreshed_adjuster["open_assignment_count"] == 0


def _inspect_claim(api, claim_id, adjuster, verified_damage_amount):
    """Schedule, start and complete a FIELD inspection on a TRIAGED claim,
    advancing the clock into the assignment window to do so."""
    assignment = validate_success(
        api.create_inspection_assignment(
            {
                "claim_id": claim_id,
                "mode": "FIELD",
                "window_start_utc": "2026-08-05T00:00:00.000Z",
                "window_end_utc": "2026-08-06T00:00:00.000Z",
                "adjuster_id": adjuster["id"],
            },
            DC,
        ),
        201,
    )
    validate_success(api.set_clock("2026-08-05T00:00:00.000Z", CM))
    adjuster_headers = make_adjuster_headers(adjuster["id"])
    validate_success(api.start_inspection(assignment["id"], adjuster_headers))
    return validate_success(
        api.complete_inspection(
            assignment["id"], {"verified_damage_amount": verified_damage_amount}, adjuster_headers
        )
    )


# ---------------------------------------------------------------------------
# Instance — corner_val_sod_anchor_survives_advance_void_and_blocks_original_examiner
# ---------------------------------------------------------------------------
def test_the_segregation_anchor_outlives_the_void_it_came_from(api):
    """PRD §3.8: "Link two-b, caused by link two, moves the claim `ADVANCE_ISSUED →
    NONE` on the payment axis when `advance_paid_total` returns to exactly 0.00 —
    and `advance_issuing_examiner_user_id` is **retained**, because a void does not
    erase the fact that this user once released money on the file."
    PRD §3.6: "The acting `X-User-ID` must differ from the claim's
    `advance_issuing_examiner_user_id`, so that whoever released advance money on
    this file is not also the person who signs it shut
    (`ERR_SEGREGATION_OF_DUTIES`, HTTP 403)."
    PRD §3.6: "Closure records the acting `X-User-ID` in `closing_examiner_user_id`
    and recomputes the event's `open_claim_count` and posture."
    PRD §3.6: "The claim's `payment_status` must be either `NONE` or `SETTLED` — a
    file sitting in `ADVANCE_ISSUED` or `PARTIAL_PAID` has money out the door and
    unfinished settlement, and closing it is refused with
    `ERR_ADVANCE_OUTSTANDING`."

    Design: Corner/validations/corner_val_sod_anchor_survives_advance_void_and_blocks_original_examiner
    """
    event = _declared_event(api, "CAT-2026-308")
    adjuster = _staff_adjuster(api, "Val Void")
    claim = _dwelling_claim(api, event["id"], "POL-308")
    validate_success(api.triage_claim(claim["id"], CE))
    advance = validate_success(
        api.create_advance_payment(
            {"claim_id": claim["id"], "requested_amount": 10000, "basis": "STRUCTURE_PARTIAL"},
            CE,
        ),
        201,
    )
    validate_success(
        api.void_advance_payment(advance["id"], {"void_reason": "Issued in error"}, CE)
    )
    _inspect_claim(api, claim["id"], adjuster, 100000)

    before_close = validate_success(api.get_claim(claim["id"], CE))
    assert before_close["payment_status"] == "NONE"
    assert_money_equals(before_close["advance_paid_total"], 0.00, "advance_paid_total")
    assert before_close["advance_issuing_examiner_user_id"] == "ce_1"
    assert_money_equals(before_close["case_reserve"], 95000.00, "case_reserve")

    blocked = api.close_claim(claim["id"], CE)
    validate_error(blocked, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, 403)

    closed = validate_success(api.close_claim(claim["id"], CE_OTHER))

    assert closed["handling_status"] == "CLOSED"
    assert closed["closing_examiner_user_id"] == "ce_2"
    assert closed["advance_issuing_examiner_user_id"] == "ce_1"


# ---------------------------------------------------------------------------
# Instance — corner_val_settled_claim_with_zero_reserve_blocks_batch_submit
# ---------------------------------------------------------------------------
def test_a_zero_reserve_settled_claim_blocks_the_batch_submission(api):
    """PRD §3.9: "`claim_count` is simply the number of claims pointing at the
    batch; `blocking_claim_count` is the number of those whose `payment_status` is
    `ADVANCE_ISSUED` **or** whose `case_reserve` is exactly zero — the first because
    money is still out on the file, the second because a file carrying no reserve at
    all is a bookkeeping error the receiving unit will not accept."
    PRD §3.9: "The batch must be `OPEN` (`ERR_BATCH_NOT_OPEN`); the parent event
    must be in `DEMOBILIZING` (`ERR_EVENT_NOT_DEMOBILIZING`), since file transfer is
    a wind-down activity; `claim_count` must be at least 1, so an empty batch is
    refused with `ERR_BATCH_EMPTY` (HTTP 422); and `blocking_claim_count` must be
    exactly zero, otherwise `ERR_BATCH_HAS_BLOCKING_CLAIMS` (HTTP 409)."
    PRD §3.8: "From `ADVANCE_ISSUED` or from `PARTIAL_PAID`, a `PAYMENT` entry whose
    `settles_claim` flag is true moves the claim to `SETTLED`, and here both source
    states also behave identically: the settling entry additionally zeroes the
    residual reserve, its case-reserve movement being the negation of the claim's
    `case_reserve` at that moment, and the same roll-ups and staling follow."

    Design: Corner/validations/corner_val_settled_claim_with_zero_reserve_blocks_batch_submit
    """
    event = _declared_event(api, "CAT-2026-309")
    adjuster = _staff_adjuster(api, "Zed Zero")
    block = validate_success(
        api.create_housing_block(
            {
                "event_id": event["id"],
                "hotel_name": "Gulf Inn",
                "city": "Tampa",
                "rooms_total": 40,
                "nightly_rate": 200,
                "block_start_date": "2026-09-01T00:00:00.000Z",
                "block_end_date": "2026-09-15T00:00:00.000Z",
            },
            DC,
        ),
        201,
    )
    validate_success(api.open_housing_block(block["id"], DC))
    claim = _dwelling_claim(api, event["id"], "POL-309")
    validate_success(api.triage_claim(claim["id"], CE))
    _inspect_claim(api, claim["id"], adjuster, 100000)

    def _payment(delta, settles):
        current = validate_success(api.get_claim(claim["id"], CE))
        return validate_success(
            api.create_reserve_entry(
                claim["id"],
                {
                    "entry_type": "PAYMENT",
                    "delta_case_reserve": -delta,
                    "delta_paid": delta,
                    "settles_claim": settles,
                    "expected_claim_version": current["version"],
                },
                CE,
            ),
            201,
        )

    _payment(40000.00, False)
    _payment(55000.00, True)
    settled = validate_success(api.get_claim(claim["id"], CE))
    assert settled["payment_status"] == "SETTLED"
    assert_money_equals(settled["case_reserve"], 0.00, "case_reserve")
    assert_money_equals(settled["paid_amount"], 95000.00, "paid_amount")
    validate_success(api.close_claim(claim["id"], CE))

    # Wind the event down so the submission's own state gates are all satisfied.
    event_now = validate_success(api.get_event(event["id"], CM))
    validate_success(
        api.create_loss_estimate(
            {
                "event_id": event["id"],
                "method": "EXPOSURE_BASED",
                "expected_event_version": event_now["version"],
            },
            CM,
        ),
        201,
    )
    validate_success(api.activate_surge(event["id"], CM))
    demobilizing = validate_success(api.demobilize_event(event["id"], CM))
    assert demobilizing["status"] == "DEMOBILIZING"

    batch = validate_success(
        api.create_batch({"event_id": event["id"], "target_unit": "PROPERTY-EAST"}, CE), 201
    )
    with_claim = validate_success(
        api.add_claim_to_batch(batch["id"], {"claim_id": claim["id"]}, CE)
    )
    assert with_claim["claim_count"] == 1
    assert with_claim["blocking_claim_count"] == 1

    response = api.submit_batch(batch["id"], CE)

    error = validate_error(response, ApiErrorId.ERR_BATCH_HAS_BLOCKING_CLAIMS, 409)
    assert error["error_id"] != ApiErrorId.ERR_BATCH_EMPTY.value
    refreshed_batch = validate_success(api.get_batch(batch["id"], CE))
    assert refreshed_batch["status"] == "OPEN"
    refreshed_claim = validate_success(api.get_claim(claim["id"], CE))
    assert refreshed_claim["handling_status"] == "CLOSED"


# ---------------------------------------------------------------------------
# Instance — corner_val_reserve_entry_to_exactly_zero_passes_one_cent_below_fails
# ---------------------------------------------------------------------------
def test_a_reserve_entry_may_land_on_zero_but_not_one_cent_below(api):
    """PRD §3.8: "One fiscal guard applies: the claim's `case_reserve` plus the
    submitted `delta_case_reserve`, rounded to 2 decimal places, must be at least
    0.00, otherwise the append is refused with `ERR_RESERVE_WOULD_GO_NEGATIVE`
    (HTTP 422)."
    PRD §3.8: "Afterwards the claim's `case_reserve` and `paid_amount`, and the
    event's `case_reserve_total`, `paid_total` and `incurred_total`, are recomputed,
    snapshots below the new high-water mark go stale, and posture is recomputed."
    PRD §2.10: "The ledger has no status filter and no time window: it is
    append-only, entries are never retracted, and a reversal is itself an entry that
    participates in the sum rather than deleting its target."

    Design: Corner/validations/corner_val_reserve_entry_to_exactly_zero_passes_one_cent_below_fails
    """
    event = _declared_event(api, "CAT-2026-310")
    claim = _dwelling_claim(api, event["id"], "POL-310")
    triaged = validate_success(api.triage_claim(claim["id"], CE))

    to_zero = validate_success(
        api.create_reserve_entry(
            claim["id"],
            {
                "entry_type": "REVISION",
                "delta_case_reserve": -65250.00,
                "delta_paid": 0,
                "expected_claim_version": triaged["version"],
            },
            CE,
        ),
        201,
    )
    assert_money_equals(to_zero["delta_case_reserve"], -65250.00, "delta_case_reserve")
    at_zero = validate_success(api.get_claim(claim["id"], CE))
    assert_money_equals(at_zero["case_reserve"], 0.00, "case_reserve")

    response = api.create_reserve_entry(
        claim["id"],
        {
            "entry_type": "REVISION",
            "delta_case_reserve": -0.01,
            "delta_paid": 0,
            "expected_claim_version": at_zero["version"],
        },
        CE,
    )

    validate_error(response, ApiErrorId.ERR_RESERVE_WOULD_GO_NEGATIVE, 422)
    unchanged = validate_success(api.get_claim(claim["id"], CE))
    assert_money_equals(unchanged["case_reserve"], 0.00, "case_reserve")
    _, meta = validate_paginated(api.list_reserve_entries(CE, params={"claim_id": claim["id"]}))
    assert meta["total_count"] == 2
    refreshed_event = validate_success(api.get_event(event["id"], CM))
    assert_money_equals(refreshed_event["case_reserve_total"], 0.00, "case_reserve_total")
    assert_money_equals(refreshed_event["incurred_total"], 0.00, "incurred_total")


# ---------------------------------------------------------------------------
# Instance — corner_val_housing_block_zero_length_window_rejected_one_day_accepted
# ---------------------------------------------------------------------------
def test_a_housing_block_needs_a_strictly_later_checkout_date(api):
    """PRD §3.4: "Creating a block names the `event_id` it supports, the
    `hotel_name` of the property, the `city` it is staged in, the `rooms_total` held
    in the block (from 0 through 400 inclusive), the per-room `nightly_rate` in whole
    dollars (which must be greater than zero), and the block's date span:
    `block_start_date` is the first night, inclusive, and `block_end_date` is the
    checkout morning — exclusive as a night but inclusive as a same-day turnover
    date — with both midnight-aligned and `block_end_date` strictly later than
    `block_start_date`."
    PRD §3.4: "From that span the system computes `block_night_count`, the number of
    whole days from `block_start_date` up to but not including `block_end_date`."
    PRD §3.4: "A newly held block is `PENDING`, with `rooms_occupied` of zero and
    `rooms_available` equal to `rooms_total`."
    PRD §2.11: "Position 16 checks interval well-formedness on bulletin creation,
    deployment creation, housing-block creation and inspection-assignment creation:
    a bulletin's `effective_to` must be strictly later than its `effective_from`, a
    deployment's or assignment's `window_end_utc` strictly later than its
    `window_start_utc`, and a block's `block_end_date` strictly later than its
    `block_start_date`, otherwise `ERR_INVALID_WINDOW` (HTTP 422)."

    Design: Corner/validations/corner_val_housing_block_zero_length_window_rejected_one_day_accepted
    """
    event = _declared_event(api, "CAT-2026-311")

    def _block(end_date):
        return api.create_housing_block(
            {
                "event_id": event["id"],
                "hotel_name": "Zero Nights Inn",
                "city": "Tampa",
                "rooms_total": 40,
                "nightly_rate": 200,
                "block_start_date": "2026-08-10T00:00:00.000Z",
                "block_end_date": end_date,
            },
            DC,
        )

    validate_error(_block("2026-08-10T00:00:00.000Z"), ApiErrorId.ERR_INVALID_WINDOW, 422)

    accepted = validate_success(_block("2026-08-11T00:00:00.000Z"), 201)

    assert accepted["status"] == "PENDING"
    assert accepted["block_night_count"] == 1
    assert accepted["rooms_total"] == 40
    assert accepted["rooms_available"] == 40
    assert accepted["rooms_occupied"] == 0
    _, meta = validate_paginated(api.list_housing_blocks(DC, params={"event_id": event["id"]}))
    assert meta["total_count"] == 1


# ---------------------------------------------------------------------------
# Instance — corner_val_bulletin_number_unique_per_event_not_globally
# ---------------------------------------------------------------------------
def test_bulletin_numbers_are_unique_per_event_not_across_events(api):
    """PRD §3.2: "Recording a bulletin takes the `event_id` of the event it
    regulates, the regulator's own `bulletin_number` (which must be unique within
    that event — a repeat is refused with `ERR_BULLETIN_NUMBER_TAKEN`), the
    `jurisdiction_state` the bulletin binds as a two-letter uppercase code, the
    `bulletin_type`, and the half-open binding window given by `effective_from` and
    `effective_to`."
    PRD §3.2: "A recorded bulletin begins in `DRAFT` with `activated_at_utc` of
    null, and lists of bulletins may be narrowed by `event_id`, `bulletin_type` and
    `status`."
    PRD §2.11: "Positions 31 through 37 are structural business constraints —
    uniqueness, adjuster assignment capacity, vendor job capacity, the reopen
    ceiling, selector pool emptiness, the empty-block rule, and the batch submission
    gates."

    Design: Corner/validations/corner_val_bulletin_number_unique_per_event_not_globally
    """
    event_a = _declared_event(api, "CAT-2026-312")
    event_b = _declared_event(api, "CAT-2026-313")

    def _bulletin(event_id):
        return api.create_bulletin(
            {
                "event_id": event_id,
                "bulletin_number": "BUL-2026-0777",
                "bulletin_type": "CANCELLATION_MORATORIUM",
                "jurisdiction_state": "FL",
                "effective_from": "2026-08-01T00:00:00.000Z",
                "effective_to": "2026-12-01T00:00:00.000Z",
            },
            CO,
        )

    first = validate_success(_bulletin(event_a["id"]), 201)
    second = validate_success(_bulletin(event_b["id"]), 201)

    assert first["status"] == "DRAFT"
    assert second["status"] == "DRAFT"
    assert first["bulletin_number"] == second["bulletin_number"]

    validate_error(_bulletin(event_a["id"]), ApiErrorId.ERR_BULLETIN_NUMBER_TAKEN, 409)

    _, meta = validate_paginated(api.list_bulletins(CO, params={"event_id": event_a["id"]}))
    assert meta["total_count"] == 1


# ---------------------------------------------------------------------------
# Instance — corner_val_duplicate_claim_key_is_policy_number_plus_loss_date
# ---------------------------------------------------------------------------
def test_duplicate_intake_is_keyed_on_policy_number_and_loss_date_together(api):
    """PRD §3.6: "Another claim already holding the same `policy_number` and
    `loss_date_utc` pair makes the intake a duplicate, refused with
    `ERR_DUPLICATE_CLAIM`."
    PRD §2.11: "Positions 31 through 37 are structural business constraints —
    uniqueness, adjuster assignment capacity, vendor job capacity, the reopen
    ceiling, selector pool emptiness, the empty-block rule, and the batch submission
    gates."

    Design: Corner/validations/corner_val_duplicate_claim_key_is_policy_number_plus_loss_date
    """
    event = _declared_event(api, "CAT-2026-314")

    first = _dwelling_claim(
        api, event["id"], "POL-900", loss_date_utc="2026-07-28T00:00:00.000Z"
    )
    second = _dwelling_claim(
        api, event["id"], "POL-900", loss_date_utc="2026-07-29T00:00:00.000Z"
    )

    # The same policy number on a different loss date is a distinct claim.
    assert first["handling_status"] == "INTAKE"
    assert second["handling_status"] == "INTAKE"
    assert first["policy_number"] == second["policy_number"]

    response = api.create_claim(
        {
            "policy_number": "POL-900",
            "loss_state": "FL",
            "loss_date_utc": "2026-07-28T00:00:00.000Z",
            "reported_loss_amount": 120000,
            "coverage_lines": [
                {
                    "coverage_code": "DWELLING",
                    "limit_amount": 400000,
                    "deductible_amount": 5000,
                    "estimated_damage_amount": 150000,
                }
            ],
            "event_id": event["id"],
            "access_status": "ACCESSIBLE",
        },
        CE,
    )

    validate_error(response, ApiErrorId.ERR_DUPLICATE_CLAIM, 409)
    _, meta = validate_paginated(api.list_claims(CE, params={"event_id": event["id"]}))
    assert meta["total_count"] == 2


# ---------------------------------------------------------------------------
# Instance — corner_val_not_assigned_adjuster_precedes_assignment_state_check
# ---------------------------------------------------------------------------
def test_ownership_is_checked_before_the_assignment_state(api):
    """PRD §2.11: "Position 17 enforces entity-backed ownership: an `Adjuster`
    starting, completing or reporting no access on an assignment must be that
    assignment's adjuster (`ERR_NOT_ASSIGNED_ADJUSTER`), and a `VendorCoordinator`
    accepting, declining or completing a vendor assignment must be that assignment's
    firm (`ERR_NOT_ASSIGNED_VENDOR`)."
    PRD §2.11: "Position 19 is the state check: the target must currently be in a
    state from which the requested transition is declared, and the error returned is
    the specific one named by that transition's preconditions rather than a generic
    one; `ERR_INVALID_STATE` (HTTP 409) is the fallback used only when a
    state-transition endpoint is invoked from a from-state that no declared
    transition covers and no more specific error applies."
    PRD §3.7: "**Starting** the inspection moves it `SCHEDULED → IN_PROGRESS`; the
    assignment must be `SCHEDULED` (`ERR_ASSIGNMENT_NOT_SCHEDULED`), the clock must
    have reached or passed `window_start_utc` (`ERR_ASSIGNMENT_WINDOW_NOT_STARTED`),
    and the adjuster's `credential_status` must be `VALID`, `EXPIRING` or `WAIVED`
    (`ERR_ADJUSTER_CREDENTIAL_INVALID`) — a licence that lapsed between scheduling
    and arrival stops the work at the door."
    PRD §3.7: "Either source state behaves identically: the adjuster's
    `open_assignment_count` and `surge_capacity_score` are recomputed, and when the
    claim has no assignment left in `SCHEDULED` or `IN_PROGRESS`, the claim regresses
    `INSPECTION_PENDING → TRIAGED` and the event's posture is recomputed — which is
    how a mass demobilization can tighten an event's posture without anyone touching
    the event."

    Design: Corner/validations/corner_val_not_assigned_adjuster_precedes_assignment_state_check
    """
    event = _declared_event(api, "CAT-2026-315")
    assigned = _staff_adjuster(api, "Ann Assigned")
    other = _staff_adjuster(api, "Otto Other")
    claim = _dwelling_claim(api, event["id"], "POL-315")
    validate_success(api.triage_claim(claim["id"], CE))
    assignment = validate_success(
        api.create_inspection_assignment(
            {
                "claim_id": claim["id"],
                "mode": "FIELD",
                "window_start_utc": "2026-08-10T00:00:00.000Z",
                "window_end_utc": "2026-08-11T00:00:00.000Z",
                "adjuster_id": assigned["id"],
            },
            DC,
        ),
        201,
    )
    cancelled = validate_success(api.cancel_inspection_assignment(assignment["id"], DC))
    assert cancelled["status"] == "CANCELLED"

    by_stranger = api.start_inspection(assignment["id"], make_adjuster_headers(other["id"]))

    error = validate_error(by_stranger, ApiErrorId.ERR_NOT_ASSIGNED_ADJUSTER, 403)
    assert error["error_id"] != ApiErrorId.ERR_ASSIGNMENT_NOT_SCHEDULED.value

    by_owner = api.start_inspection(assignment["id"], make_adjuster_headers(assigned["id"]))
    validate_error(by_owner, ApiErrorId.ERR_ASSIGNMENT_NOT_SCHEDULED, 409)

    refreshed_assignment = validate_success(api.get_inspection_assignment(assignment["id"], DC))
    assert refreshed_assignment["status"] == "CANCELLED"
    refreshed_claim = validate_success(api.get_claim(claim["id"], CE))
    assert refreshed_claim["handling_status"] == "TRIAGED"
    refreshed_adjuster = validate_success(api.get_adjuster(assigned["id"], DC))
    assert refreshed_adjuster["open_assignment_count"] == 0


# ---------------------------------------------------------------------------
# Instance — corner_val_vendor_capacity_checked_before_new_job_counted
# ---------------------------------------------------------------------------
def test_vendor_capacity_is_evaluated_before_the_new_job_is_counted(api):
    """PRD §3.9: "Whether chosen or pinned, the firm's `service_states` must contain
    the claim's `loss_state` (`ERR_VENDOR_NOT_LICENSED_IN_STATE`) and its
    `open_job_count` must be strictly below `max_concurrent_jobs`
    (`ERR_VENDOR_CAPACITY_EXCEEDED`)."
    PRD §3.9: "A created assignment is `DISPATCHED`, stamps `dispatched_at_utc` at
    the current logical-clock instant, records `EXPLICIT_VENDOR` or
    `SELECTOR_RANKED` in `selection_reason`, and triggers a recompute of the firm's
    `open_job_count`."
    PRD §3.9: "Occupancy then drives the firm automatically: when a job acceptance
    drives `open_job_count` to exactly `max_concurrent_jobs`, the firm moves
    `ACTIVATED → CAPACITY_HOLD`; when a job leaves the open population and
    `open_job_count` falls back below the ceiling, the firm moves `CAPACITY_HOLD →
    ACTIVATED`."

    Design: Corner/validations/corner_val_vendor_capacity_checked_before_new_job_counted
    """
    event = _declared_event(api, "CAT-2026-316")
    firm = validate_success(
        api.create_vendor_firm(
            {
                "firm_name": "Solo Tarp Crew",
                "vendor_type": "TARP",
                "service_states": ["FL"],
                "max_concurrent_jobs": 1,
                "performance_score": 88.00,
            },
            make_vendor_coordinator_headers("vc_seed"),
        ),
        201,
    )
    own_headers = make_vendor_coordinator_headers(firm["id"])
    validate_success(api.activate_vendor_firm(firm["id"], {"event_id": event["id"]}, own_headers))
    claim_a = _dwelling_claim(api, event["id"], "POL-316-A")
    claim_b = _dwelling_claim(api, event["id"], "POL-316-B")

    def _dispatch(claim_id):
        return api.create_vendor_assignment(
            {
                "claim_id": claim_id,
                "scope_amount": 9000,
                "required_vendor_type": "TARP",
                "vendor_firm_id": firm["id"],
            },
            CE,
        )

    first = validate_success(_dispatch(claim_a["id"]), 201)
    assert first["status"] == "DISPATCHED"
    assert first["selection_reason"] == "EXPLICIT_VENDOR"

    # The single open job already occupies the whole ceiling.
    validate_error(_dispatch(claim_b["id"]), ApiErrorId.ERR_VENDOR_CAPACITY_EXCEEDED, 409)

    refreshed_firm = validate_success(api.get_vendor_firm(firm["id"], own_headers))
    assert refreshed_firm["open_job_count"] == 1
    assert refreshed_firm["status"] == "ACTIVATED"
    _, meta = validate_paginated(
        api.list_vendor_assignments(CE, params={"claim_id": claim_b["id"]})
    )
    assert meta["total_count"] == 0
