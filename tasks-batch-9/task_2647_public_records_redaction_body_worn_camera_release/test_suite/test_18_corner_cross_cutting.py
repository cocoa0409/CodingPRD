"""Cross-cutting layers: optimistic concurrency, reconciliation and immediacy.

The two version-guarded writes are pinned on both faces — the 412 that costs the
caller nothing and the retry that succeeds once the version is re-read. The
retention lock walks both branches of its disjunction, the two estimate bases
diverge and then reconverge on the same data, and the release and invoice writes
are shown to carry every derived field in their own response bodies.
"""

from prd_bench_local_runner.testing import get_success_data, validate_error

from test_helpers.api_errors import (
    ERR_ASSET_STATE_INVALID,
    ERR_RETENTION_HOLD_ACTIVE,
    ERR_STALE_REQUEST_VERSION,
)
from test_helpers.assertions import (
    assert_created,
    assert_fields,
    assert_ledger_conservation,
    assert_list_response,
    assert_modified,
    assert_money_is_integer_cents,
    assert_total_count,
    assert_waiver_pct,
)
from test_helpers.factories import (
    fee_estimate_payload,
    hold_release_payload,
    inclusion_payload,
    invoice_payload,
    purge_payload,
    qa_outcome_payload,
    release_package_payload,
    scope_clarification_payload,
)
from test_helpers.fixtures import (
    adjudicate,
    assert_claim,
    attach_record,
    clarify_scope,
    create_asset,
    create_estimate,
    create_request,
    create_requester,
    create_staff,
    get_asset,
    get_claim,
    get_hold,
    get_record,
    get_request,
    get_staff,
    open_task,
    place_hold,
    record_verdict,
    request_version,
    rule_inclusion,
    submit_for_qa,
)
from test_helpers.test_users import (
    CLERK_HEADERS,
    SUPERVISOR_HEADERS,
    make_counsel_headers,
    make_reviewer_headers,
)


def _responsive_half_hour_request(api):
    """A RESPONSIVE 30-minute ROUTINE record whose request has been clarified once.

    The version the intake call returned is retained deliberately: the
    clarification and the inclusion ruling have both moved it on since.
    """
    requester = create_requester(api, "Pat Public", "pat@example.org", "GENERAL_PUBLIC")
    asset = create_asset(
        api,
        incident_number="INC-2026-0670",
        device_serial="AXON-0670",
        officer_badge="B-1169",
        recorded_start_at="2026-06-25T09:00:00Z",
        duration_ms=1800000,
        classification="ROUTINE",
        retention_category="INVESTIGATIVE_3Y",
        scheduled_purge_at="2029-06-25T00:00:00Z",
    )
    request = create_request(
        api,
        requester["id"],
        subject_incident_number="INC-2026-0670",
        requested_date_from="2026-06-25T00:00:00Z",
        requested_date_to="2026-06-26T00:00:00Z",
        scope_narrative="Half an hour of BWC video",
    )
    clarify_scope(
        api,
        request["id"],
        scope_narrative="The single half-hour recording",
        requested_date_from="2026-06-25T00:00:00Z",
        requested_date_to="2026-06-25T23:59:59Z",
    )
    record = attach_record(api, request["id"], asset["id"])
    rule_inclusion(api, record["id"], "RESPONSIVE")
    return {
        "request_id": request["id"],
        "record_id": record["id"],
        "intake_version": request["version"],
    }


def test_fee_estimate_refuses_the_intake_version_and_accepts_the_re_read_one(api):
    """The stale write bumps nothing; the same call with the fresh version prices 500 cents.

    PRD: "This call likewise requires `expected_request_version` to match the addressed request's current `version`, and a mismatch is rejected with `ERR_STALE_REQUEST_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/stale_expected_request_version_on_fee_estimate_create_returns_412
    """
    scenario = _responsive_half_hour_request(api)

    refused = api.create_fee_estimate(
        scenario["request_id"],
        fee_estimate_payload(scenario["intake_version"], "PRESUMPTIVE", "DVD"),
        CLERK_HEADERS,
    )

    validate_error(refused, ERR_STALE_REQUEST_VERSION, 412)
    assert_total_count(api.list_fee_estimates(scenario["request_id"], CLERK_HEADERS), 0)
    fresh_version = request_version(api, scenario["request_id"])
    assert fresh_version > scenario["intake_version"]

    accepted = api.create_fee_estimate(
        scenario["request_id"],
        fee_estimate_payload(fresh_version, "PRESUMPTIVE", "DVD"),
        CLERK_HEADERS,
    )

    estimate = assert_created(accepted)
    assert_fields(
        estimate,
        sequence_number=1,
        status="ACTIVE",
        basis="PRESUMPTIVE",
        projected_review_minutes=30,
        projected_burden_minutes=8,
        billable_minutes=0,
        estimated_labor_cents=0,
        media_production_cents=500,
        subtotal_cents=500,
        waiver_credit_cents=0,
        estimated_total_cents=500,
        deposit_required_cents=0,
    )
    assert_waiver_pct(estimate, "effective_waiver_pct", 0.00)
    assert_money_is_integer_cents(
        estimate,
        "estimated_labor_cents",
        "media_production_cents",
        "subtotal_cents",
        "waiver_credit_cents",
        "estimated_total_cents",
        "deposit_required_cents",
    )
    request = get_request(api, scenario["request_id"])
    assert_fields(
        request,
        fee_status="ESTIMATED",
        estimated_total_cents=500,
        deposit_required_cents=0,
        deposit_due_at=None,
        version=fresh_version + 1,
    )


def test_a_consumed_version_cannot_be_replayed_and_the_mirror_holds(api):
    """The version the accepted estimate spent is itself stale one call later.

    PRD: "The request's `estimated_total_cents` and `deposit_required_cents` mirror the new estimate's corresponding figures — and are 0 whenever no `ACTIVE` estimate exists — and the request's `version` increases by 1."

    Design: Corner/cross_cutting_complexity_layers/stale_expected_request_version_on_fee_estimate_create_returns_412
    """
    scenario = _responsive_half_hour_request(api)
    spent_version = request_version(api, scenario["request_id"])
    create_estimate(
        api,
        scenario["request_id"],
        "PRESUMPTIVE",
        "DVD",
        expected_request_version=spent_version,
    )

    replay = api.create_fee_estimate(
        scenario["request_id"],
        fee_estimate_payload(spent_version, "PRESUMPTIVE", "DVD"),
        CLERK_HEADERS,
    )

    validate_error(replay, ERR_STALE_REQUEST_VERSION, 412)
    assert_total_count(api.list_fee_estimates(scenario["request_id"], CLERK_HEADERS), 1)
    assert_fields(
        get_request(api, scenario["request_id"]),
        estimated_total_cents=500,
        deposit_required_cents=0,
        fee_status="ESTIMATED",
        version=spent_version + 1,
    )


def _unclarified_request(api):
    """A request straight out of intake, version 1, with no clarification yet."""
    requester = create_requester(api, "Mo Media", "mo@dailywire.example", "MEDIA")
    request = create_request(
        api,
        requester["id"],
        subject_incident_number="INC-2026-0671",
        requested_date_from="2026-06-24T00:00:00Z",
        requested_date_to="2026-06-25T00:00:00Z",
        scope_narrative="Everything you hold on the arrest",
    )
    return {"request_id": request["id"], "version": request["version"]}


def test_replayed_scope_clarification_costs_neither_version_nor_clarification_slot(api):
    """The first clarification lands; the identical retry is refused with 412.

    PRD: "The request must therefore carry `expected_request_version` matching the addressed request's current `version`; if the two differ the write is rejected with `ERR_STALE_REQUEST_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/stale_expected_request_version_on_scope_clarification_returns_412
    """
    scenario = _unclarified_request(api)
    payload = scope_clarification_payload(
        scenario["version"],
        scope_narrative="Narrowed to the arrest",
        requested_date_from="2026-06-24T00:00:00Z",
        requested_date_to="2026-06-24T23:59:59Z",
    )

    first = assert_modified(api.clarify_scope(scenario["request_id"], payload, CLERK_HEADERS))

    assert_fields(
        first,
        processing_status="SCOPING",
        scope_clarification_count=1,
        scope_narrative="Narrowed to the arrest",
        statutory_deadline_at="2026-08-21T00:00:00Z",
        version=scenario["version"] + 1,
    )

    replay = api.clarify_scope(scenario["request_id"], payload, CLERK_HEADERS)

    validate_error(replay, ERR_STALE_REQUEST_VERSION, 412)
    assert_fields(
        get_request(api, scenario["request_id"]),
        processing_status="SCOPING",
        scope_clarification_count=1,
        version=scenario["version"] + 1,
    )


def test_the_second_clarification_with_the_fresh_version_re_strikes_the_deadline(api):
    """Re-reading the version lets the supervisor clarify again and grant five days.

    PRD: "The call then increments `scope_clarification_count` by 1, re-strikes `statutory_deadline_at` with the new extension, increments the request's `version` by 1, and marks any fee estimate on this request whose `status` is `ACTIVE` as `STALE`, because the scope it priced no longer exists."

    Design: Corner/cross_cutting_complexity_layers/stale_expected_request_version_on_scope_clarification_returns_412
    """
    scenario = _unclarified_request(api)
    clarify_scope(
        api,
        scenario["request_id"],
        expected_request_version=scenario["version"],
        scope_narrative="Narrowed to the arrest",
        requested_date_from="2026-06-24T00:00:00Z",
        requested_date_to="2026-06-24T23:59:59Z",
    )
    fresh_version = request_version(api, scenario["request_id"])

    response = api.clarify_scope(
        scenario["request_id"],
        scope_clarification_payload(
            fresh_version,
            scope_narrative="Narrowed again to the transport leg",
            requested_date_from="2026-06-24T00:00:00Z",
            requested_date_to="2026-06-24T11:00:00Z",
            extension_days_granted=5,
        ),
        SUPERVISOR_HEADERS,
    )

    clarified = assert_modified(response)
    assert_fields(
        clarified,
        processing_status="SCOPING",
        scope_clarification_count=2,
        scope_narrative="Narrowed again to the transport leg",
        requested_date_to="2026-06-24T11:00:00Z",
        extension_days_granted=5,
        statutory_deadline_at="2026-08-26T00:00:00Z",
        version=fresh_version + 1,
    )


def _overdue_recording_referenced_by_two_requests(api):
    """One past-due recording sitting as a CANDIDATE record on two scoped requests.

    No litigation hold exists anywhere, so the only thing that can lock this
    recording is the second branch of the `retention_locked` disjunction.
    """
    counsel = create_staff(api, "Dana Counsel", "COUNSEL", 3)
    requester = create_requester(api, "Pat Public", "pat@example.org", "GENERAL_PUBLIC")
    asset = create_asset(
        api,
        incident_number="INC-2026-0672",
        device_serial="AXON-0672",
        officer_badge="B-1170",
        recorded_start_at="2026-01-16T04:00:00Z",
        duration_ms=1800000,
        classification="ROUTINE",
        retention_category="NON_EVIDENTIARY_180D",
        scheduled_purge_at="2026-07-15T00:00:00Z",
    )
    request_ids = []
    for index, narrative in enumerate(("First filer's copy", "Second filer's copy")):
        request = create_request(
            api,
            requester["id"],
            subject_incident_number="INC-2026-0672",
            requested_date_from="2026-01-16T00:00:00Z",
            requested_date_to="2026-01-17T00:00:00Z",
            scope_narrative=narrative,
        )
        clarify_scope(
            api,
            request["id"],
            scope_narrative=f"Narrowed scope {index + 1}",
            requested_date_from="2026-01-16T00:00:00Z",
            requested_date_to="2026-01-16T23:59:59Z",
        )
        request_ids.append(request["id"])
    return {
        "counsel_id": counsel["id"],
        "asset": asset,
        "asset_id": asset["id"],
        "request_ids": request_ids,
    }


def _exclude_both_references(api, scenario):
    """Attach the recording to both requests and rule both records EXCLUDED."""
    record_ids = [
        attach_record(api, request_id, scenario["asset_id"])["id"]
        for request_id in scenario["request_ids"]
    ]
    for record_id in record_ids:
        rule_inclusion(api, record_id, "EXCLUDED")
    return record_ids


def test_the_open_request_branch_alone_locks_the_recording(api):
    """With no hold in existence, attachment is what flips retention_locked true.

    PRD: "`retention_locked` on a recording is true exactly when at least one litigation hold with `status` `ACTIVE` carries a `scope_incident_number` equal to the recording's `incident_number`, or at least one responsive record references the recording with `inclusion_status` among `CANDIDATE`, `RESPONSIVE` and `WITHHELD_IN_FULL` on a request whose `processing_status` is none of `RELEASED`, `DENIED` and `CLOSED`."

    Design: Corner/cross_cutting_complexity_layers/retention_locked_reconciles_across_both_of_its_or_branches
    """
    scenario = _overdue_recording_referenced_by_two_requests(api)
    assert_fields(
        scenario["asset"],
        retention_locked=False,
        disposition_state="SCHEDULED",
        suspended_by_hold_id=None,
    )

    first_record = attach_record(api, scenario["request_ids"][0], scenario["asset_id"])

    assert_fields(first_record, inclusion_status="CANDIDATE", release_posture="OPEN")
    assert_fields(
        get_asset(api, scenario["asset_id"]),
        retention_locked=True,
        disposition_state="SCHEDULED",
        suspended_by_hold_id=None,
    )

    attach_record(api, scenario["request_ids"][1], scenario["asset_id"])

    assert get_asset(api, scenario["asset_id"])["retention_locked"] is True
    for request_id in scenario["request_ids"]:
        assert get_request(api, request_id)["responsive_record_count"] == 1


def test_the_lock_survives_the_first_exclusion_and_clears_on_the_second(api):
    """Only when no reference remains does the record branch stop locking.

    PRD: "A ruling of `EXCLUDED` moves the record `CANDIDATE → EXCLUDED`, which is terminal, recomputes the request's `responsive_record_count`, and recomputes the recording's `retention_locked`, since the excluded record no longer justifies locking it."

    Design: Corner/cross_cutting_complexity_layers/retention_locked_reconciles_across_both_of_its_or_branches
    """
    scenario = _overdue_recording_referenced_by_two_requests(api)
    record_ids = [
        attach_record(api, request_id, scenario["asset_id"])["id"]
        for request_id in scenario["request_ids"]
    ]

    first_ruling = assert_modified(
        api.rule_inclusion(record_ids[0], inclusion_payload("EXCLUDED"), CLERK_HEADERS)
    )

    assert first_ruling["inclusion_status"] == "EXCLUDED"
    assert get_request(api, scenario["request_ids"][0])["responsive_record_count"] == 0
    assert get_asset(api, scenario["asset_id"])["retention_locked"] is True

    assert_modified(
        api.rule_inclusion(record_ids[1], inclusion_payload("EXCLUDED"), CLERK_HEADERS)
    )

    assert get_request(api, scenario["request_ids"][1])["responsive_record_count"] == 0
    assert_fields(
        get_asset(api, scenario["asset_id"]),
        retention_locked=False,
        disposition_state="SCHEDULED",
        suspended_by_hold_id=None,
    )


def test_destruction_reports_the_lock_first_and_the_suspension_afterwards(api):
    """The same purge call names the open request, then names the hold's suspension.

    PRD: "A recording that is `SUSPENDED` or already `PURGED` is refused with `ERR_ASSET_STATE_INVALID`; one that is still locked — whether by an `ACTIVE` matching hold or by an open request — is refused with `ERR_RETENTION_HOLD_ACTIVE`; and one whose purge date has not yet arrived is refused with `ERR_PURGE_NOT_DUE`."

    Design: Corner/cross_cutting_complexity_layers/retention_locked_reconciles_across_both_of_its_or_branches
    """
    scenario = _overdue_recording_referenced_by_two_requests(api)
    record = attach_record(api, scenario["request_ids"][0], scenario["asset_id"])

    locked_refusal = api.purge_video_asset(
        scenario["asset_id"], purge_payload("180-day schedule elapsed"), SUPERVISOR_HEADERS
    )

    validate_error(locked_refusal, ERR_RETENTION_HOLD_ACTIVE, 409)
    assert get_asset(api, scenario["asset_id"])["disposition_state"] == "SCHEDULED"

    rule_inclusion(api, record["id"], "EXCLUDED")
    place_hold(
        api,
        scenario["counsel_id"],
        matter_number="LIT-2026-0672",
        scope_incident_number="INC-2026-0672",
        hold_type="LITIGATION",
    )

    suspended_refusal = api.purge_video_asset(
        scenario["asset_id"], purge_payload("180-day schedule elapsed"), SUPERVISOR_HEADERS
    )

    validate_error(suspended_refusal, ERR_ASSET_STATE_INVALID, 409)
    assert_fields(
        get_asset(api, scenario["asset_id"]),
        disposition_state="SUSPENDED",
        retention_locked=True,
    )


def test_releasing_the_only_hold_recomputes_the_lock_from_its_full_definition(api):
    """With both references excluded, lifting the hold leaves nothing to lock the recording.

    PRD: "In either branch `retention_locked` is recomputed from its full definition, so a recording still referenced by an open request remains locked even with every hold gone."

    Design: Corner/cross_cutting_complexity_layers/retention_locked_reconciles_across_both_of_its_or_branches
    """
    scenario = _overdue_recording_referenced_by_two_requests(api)
    _exclude_both_references(api, scenario)
    hold = place_hold(
        api,
        scenario["counsel_id"],
        matter_number="LIT-2026-0672",
        scope_incident_number="INC-2026-0672",
        hold_type="LITIGATION",
    )
    assert_fields(
        get_asset(api, scenario["asset_id"]),
        retention_locked=True,
        disposition_state="SUSPENDED",
        suspended_by_hold_id=hold["id"],
    )
    assert get_hold(api, hold["id"])["suspended_asset_count"] == 1

    released = get_success_data(
        api.release_litigation_hold(
            hold["id"],
            hold_release_payload("Matter dismissed"),
            make_counsel_headers(scenario["counsel_id"]),
        )
    )

    assert_fields(
        released,
        status="RELEASED",
        released_at="2026-08-01T00:00:00Z",
        suspended_asset_count=0,
    )
    assert_fields(
        get_asset(api, scenario["asset_id"]),
        retention_locked=False,
        disposition_state="SCHEDULED",
        suspended_by_hold_id=None,
    )

    purged = get_success_data(
        api.purge_video_asset(
            scenario["asset_id"], purge_payload("180-day schedule elapsed"), SUPERVISOR_HEADERS
        )
    )

    assert purged["disposition_state"] == "PURGED"


def _hour_long_record_with_a_medical_claim(api):
    """A RESPONSIVE hour of footage carrying one ASSERTED medical partial-redaction claim.

    The baseline obscuration is 15 minutes and the claim projects 30 more, so the
    presumptive and adjudicated burdens are deliberately far apart.
    """
    counsel_a = create_staff(api, "Dana Counsel", "COUNSEL", 3)
    counsel_b = create_staff(api, "Ray Counsel", "COUNSEL", 3)
    requester = create_requester(api, "Pat Public", "pat@example.org", "GENERAL_PUBLIC")
    asset = create_asset(
        api,
        incident_number="INC-2026-0673",
        device_serial="AXON-0673",
        officer_badge="B-1171",
        recorded_start_at="2026-06-26T09:00:00Z",
        duration_ms=3600000,
        classification="ROUTINE",
        retention_category="INVESTIGATIVE_3Y",
        scheduled_purge_at="2029-06-26T00:00:00Z",
    )
    request = create_request(
        api,
        requester["id"],
        subject_incident_number="INC-2026-0673",
        requested_date_from="2026-06-26T00:00:00Z",
        requested_date_to="2026-06-27T00:00:00Z",
        scope_narrative="The full hour of footage",
    )
    clarify_scope(
        api,
        request["id"],
        scope_narrative="The full hour, medical detail redacted",
        requested_date_from="2026-06-26T00:00:00Z",
        requested_date_to="2026-06-26T23:59:59Z",
    )
    record = attach_record(api, request["id"], asset["id"])
    rule_inclusion(api, record["id"], "RESPONSIVE")
    claim = assert_claim(api, record["id"], counsel_a["id"], "MEDICAL", "PARTIAL_REDACT")
    return {
        "request_id": request["id"],
        "record_id": record["id"],
        "claim_id": claim["id"],
        "counsel_b_id": counsel_b["id"],
    }


def test_the_presumptive_quote_prices_the_worst_case_burden(api):
    """PRESUMPTIVE totals the presumptive burden, so the asserted claim is paid for.

    PRD: "**Third**, `projected_burden_minutes` is the total over the labour set of `presumptive_burden_minutes` when `basis` is `PRESUMPTIVE`, or of `adjudicated_burden_minutes` when `basis` is `ADJUDICATED`."

    Design: Corner/cross_cutting_complexity_layers/withdrawing_a_claim_stales_the_quote_and_the_two_bases_reconverge
    """
    scenario = _hour_long_record_with_a_medical_claim(api)
    assert_fields(
        get_record(api, scenario["record_id"]),
        estimated_review_minutes=60,
        presumptive_burden_minutes=45,
        adjudicated_burden_minutes=15,
        release_posture="RESTRICTED",
        unadjudicated_claim_count=1,
    )

    response = api.create_fee_estimate(
        scenario["request_id"],
        fee_estimate_payload(
            request_version(api, scenario["request_id"]), "PRESUMPTIVE", "DIGITAL_DOWNLOAD"
        ),
        CLERK_HEADERS,
    )

    estimate = assert_created(response)
    assert_fields(
        estimate,
        sequence_number=1,
        status="ACTIVE",
        basis="PRESUMPTIVE",
        projected_review_minutes=60,
        projected_burden_minutes=45,
        billable_minutes=45,
        estimated_labor_cents=3150,
        media_production_cents=0,
        subtotal_cents=3150,
        waiver_credit_cents=0,
        estimated_total_cents=3150,
        deposit_required_cents=0,
    )
    assert_fields(
        get_request(api, scenario["request_id"]),
        fee_status="ESTIMATED",
        estimated_total_cents=3150,
    )


def test_withdrawing_the_claim_drops_the_presumptive_burden_and_stales_the_quote(api):
    """The worst-case figure falls to the baseline and the quote that priced it goes stale.

    PRD: "The parent record re-derives `release_posture`, `presumptive_burden_minutes` **and** `adjudicated_burden_minutes`, and both the record's and the request's `unadjudicated_claim_count` decrement."

    Design: Corner/cross_cutting_complexity_layers/withdrawing_a_claim_stales_the_quote_and_the_two_bases_reconverge
    """
    scenario = _hour_long_record_with_a_medical_claim(api)
    estimate = create_estimate(api, scenario["request_id"], "PRESUMPTIVE", "DIGITAL_DOWNLOAD")

    adjudicate(api, scenario["claim_id"], scenario["counsel_b_id"], "WITHDRAWN")

    assert_fields(
        get_claim(api, scenario["claim_id"]),
        status="WITHDRAWN",
        adjudicated_by_staff_id=scenario["counsel_b_id"],
    )
    assert_fields(
        get_record(api, scenario["record_id"]),
        presumptive_burden_minutes=15,
        adjudicated_burden_minutes=15,
        release_posture="OPEN",
        unadjudicated_claim_count=0,
    )
    assert_fields(
        get_request(api, scenario["request_id"]),
        processing_status="RELEASE_READY",
        unadjudicated_claim_count=0,
    )
    rows, _meta = assert_list_response(
        api.list_fee_estimates(scenario["request_id"], CLERK_HEADERS)
    )
    stale = {row["id"]: row for row in rows}[estimate["id"]]
    assert_fields(stale, status="STALE", estimated_total_cents=3150)


def test_the_two_bases_reconverge_once_the_claim_is_gone(api):
    """A stale quote mirrors nothing, and the re-quotes on either basis both land on 1050.

    PRD: "Every estimate on the request whose `status` is `ACTIVE` or `STALE` moves to `SUPERSEDED`, the new estimate is created at `status` `ACTIVE`, and its `sequence_number` is the count of prior estimates on the request plus one, so the first estimate is number 1."

    Design: Corner/cross_cutting_complexity_layers/withdrawing_a_claim_stales_the_quote_and_the_two_bases_reconverge
    """
    scenario = _hour_long_record_with_a_medical_claim(api)
    first = create_estimate(api, scenario["request_id"], "PRESUMPTIVE", "DIGITAL_DOWNLOAD")
    adjudicate(api, scenario["claim_id"], scenario["counsel_b_id"], "WITHDRAWN")
    assert get_request(api, scenario["request_id"])["estimated_total_cents"] == 0
    middle_version = request_version(api, scenario["request_id"])

    second = assert_created(
        api.create_fee_estimate(
            scenario["request_id"],
            fee_estimate_payload(middle_version, "ADJUDICATED", "DIGITAL_DOWNLOAD"),
            CLERK_HEADERS,
        )
    )

    assert_fields(
        second,
        sequence_number=2,
        status="ACTIVE",
        basis="ADJUDICATED",
        projected_review_minutes=60,
        projected_burden_minutes=15,
        billable_minutes=15,
        estimated_labor_cents=1050,
        subtotal_cents=1050,
        estimated_total_cents=1050,
        deposit_required_cents=0,
    )
    assert first["estimated_total_cents"] - second["estimated_total_cents"] == 2100
    late_version = request_version(api, scenario["request_id"])
    assert late_version == middle_version + 1

    third = assert_created(
        api.create_fee_estimate(
            scenario["request_id"],
            fee_estimate_payload(late_version, "PRESUMPTIVE", "DIGITAL_DOWNLOAD"),
            CLERK_HEADERS,
        )
    )

    assert_fields(
        third,
        sequence_number=3,
        status="ACTIVE",
        basis="PRESUMPTIVE",
        projected_burden_minutes=15,
        estimated_total_cents=1050,
    )
    rows, _meta = assert_total_count(
        api.list_fee_estimates(scenario["request_id"], CLERK_HEADERS), 3
    )
    by_id = {row["id"]: row for row in rows}
    assert by_id[first["id"]]["status"] == "SUPERSEDED"
    assert by_id[second["id"]]["status"] == "SUPERSEDED"
    assert by_id[third["id"]]["status"] == "ACTIVE"
    assert_fields(
        get_request(api, scenario["request_id"]),
        fee_status="ESTIMATED",
        estimated_total_cents=1050,
    )


def _submitted_face_task(api):
    """One hour of footage carrying a single QA_PENDING 20-minute face pass."""
    tech = create_staff(api, "Tess Tech", "TECHNICIAN", 1)
    reviewer = create_staff(api, "Quinn Review", "REVIEWER", 2)
    requester = create_requester(api, "Pat Public", "pat@example.org", "GENERAL_PUBLIC")
    asset = create_asset(
        api,
        incident_number="INC-2026-0674",
        device_serial="AXON-0674",
        officer_badge="B-1172",
        recorded_start_at="2026-06-27T10:00:00Z",
        duration_ms=3600000,
        classification="ROUTINE",
        retention_category="INVESTIGATIVE_3Y",
        scheduled_purge_at="2029-06-27T00:00:00Z",
    )
    request = create_request(
        api,
        requester["id"],
        subject_incident_number="INC-2026-0674",
        requested_date_from="2026-06-27T00:00:00Z",
        requested_date_to="2026-06-28T00:00:00Z",
        scope_narrative="The hour of footage, faces obscured",
    )
    clarify_scope(
        api,
        request["id"],
        scope_narrative="The hour of footage, faces obscured",
        requested_date_from="2026-06-27T00:00:00Z",
        requested_date_to="2026-06-27T23:59:59Z",
    )
    record = attach_record(api, request["id"], asset["id"])
    rule_inclusion(api, record["id"], "RESPONSIVE")
    task = open_task(api, record["id"], tech["id"], "FACE", 0, 1200000)
    submit_for_qa(
        api, task["id"], tech["id"], reviewer["id"], 20,
        "2026-08-03T09:00:00Z", "2026-08-03T09:30:00Z",
    )
    return {
        "request_id": request["id"],
        "record_id": record["id"],
        "asset_id": asset["id"],
        "task_id": task["id"],
        "reviewer_id": reviewer["id"],
    }


def _request_ready_to_release_with_one_approved_task(api):
    """The same task passed by its reviewer, priced by an ACTIVE 1050-cent quote."""
    scenario = _submitted_face_task(api)
    record_verdict(api, scenario["task_id"], scenario["reviewer_id"], "PASS")
    estimate = create_estimate(
        api, scenario["request_id"], "ADJUDICATED", "DIGITAL_DOWNLOAD"
    )
    scenario["estimate_id"] = estimate["id"]
    scenario["estimate_total"] = estimate["estimated_total_cents"]
    return scenario


def test_the_release_response_already_carries_every_field_it_moved(api):
    """The package body and the very next reads of request, record and recording agree.

    PRD: "When an operation mutates several entities, every one of those mutations is visible to the very next read, and every derived field on every touched entity is brought into agreement before the response is written."

    Design: Corner/consistency_model/every_derived_field_is_already_correct_in_the_causing_response
    """
    scenario = _request_ready_to_release_with_one_approved_task(api)

    response = api.create_release_package(
        scenario["request_id"], release_package_payload("DIGITAL_DOWNLOAD"), CLERK_HEADERS
    )

    package = assert_created(response)
    assert_fields(
        package,
        media_type="DIGITAL_DOWNLOAD",
        included_record_count=1,
        produced_minutes=60,
        disc_count=0,
        production_cost_cents=0,
        package_kind="FINAL",
        released_at="2026-08-01T00:00:00Z",
    )
    assert_fields(
        get_request(api, scenario["request_id"]),
        processing_status="RELEASED",
        billable_labor_minutes=20,
    )
    assert_fields(
        get_record(api, scenario["record_id"]),
        inclusion_status="RELEASED",
        release_posture="OPEN",
        approved_labor_minutes=20,
        redacted_segment_ms=1200000,
        released_at="2026-08-01T00:00:00Z",
    )
    assert get_asset(api, scenario["asset_id"])["retention_locked"] is False


def test_the_invoice_response_already_carries_the_measured_total(api):
    """The invoice disagrees with the quote by design and settles the fee fields at once.

    PRD: "There is no deferred settlement and no eventual consistency anywhere in this system."

    Design: Corner/consistency_model/every_derived_field_is_already_correct_in_the_causing_response
    """
    scenario = _request_ready_to_release_with_one_approved_task(api)
    assert scenario["estimate_total"] == 1050
    get_success_data(
        api.create_release_package(
            scenario["request_id"], release_package_payload("DIGITAL_DOWNLOAD"), CLERK_HEADERS
        )
    )
    assert get_request(api, scenario["request_id"])["fee_status"] == "ESTIMATED"

    invoiced = get_success_data(
        api.issue_invoice(
            scenario["request_id"], invoice_payload("Final cost-recovery invoice"), SUPERVISOR_HEADERS
        )
    )

    assert_fields(invoiced, invoiced_total_cents=1400, fee_status="INVOICED")
    reread = get_request(api, scenario["request_id"])
    assert_fields(
        reread,
        invoiced_total_cents=1400,
        fee_recognized_cents=1400,
        deposit_paid_cents=0,
        waiver_credit_total_cents=0,
        deposit_balance_cents=-1400,
        fee_status="INVOICED",
        processing_status="RELEASED",
    )
    assert_ledger_conservation(reread)


def test_the_verdict_response_already_carries_the_reconciled_labour_rollup(api):
    """The passing verdict's own body holds the frozen minutes the rollups then repeat.

    PRD: "Both then reconcile the labour rollup: a record's `approved_labor_minutes` is the total `approved_labor_minutes` of the tasks on it whose `status` is `APPROVED`, its `redacted_segment_ms` is the total of `clip_end_ms` minus `clip_start_ms` over those same approved tasks, and the request's `billable_labor_minutes` is the total of `approved_labor_minutes` across every one of its records — including `EXCLUDED` ones, whose tasks are cancelled and therefore contribute nothing anyway."

    Design: Corner/consistency_model/every_derived_field_is_already_correct_in_the_causing_response
    """
    scenario = _submitted_face_task(api)
    assert_fields(
        get_record(api, scenario["record_id"]),
        approved_labor_minutes=0,
        redacted_segment_ms=0,
    )
    assert get_request(api, scenario["request_id"])["billable_labor_minutes"] == 0

    response = api.record_qa_outcome(
        scenario["task_id"],
        qa_outcome_payload("PASS"),
        make_reviewer_headers(scenario["reviewer_id"]),
    )

    approved = assert_modified(response)
    assert_fields(approved, status="APPROVED", approved_labor_minutes=20)
    assert approved["defect_codes"] == []
    assert_fields(
        get_record(api, scenario["record_id"]),
        approved_labor_minutes=20,
        redacted_segment_ms=1200000,
    )
    assert_fields(
        get_request(api, scenario["request_id"]),
        billable_labor_minutes=20,
        processing_status="RELEASE_READY",
    )
    assert get_staff(api, scenario["reviewer_id"])["open_qa_assignment_count"] == 0
