"""
Non-linear lifecycles of the Digital Estate Fiduciary Access API.

The contracts exercised here are the ones whose state machines are not simple
forward chains: the platform request's information cycle loops back on itself
three times and then caps, a disposition election enters the machine at a
different initial node depending on the disposition elected and lands on a
posture with no reverse edge, and the estate's administration phase walks
backwards as well as forwards before closure pins it for good.
"""

from datetime import datetime, timedelta

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    factories as f,
    fixtures,
    make_fiduciary_headers,
    make_platform_compliance_headers,
)
from test_helpers.api_errors import (
    ERR_ESTATE_CLOSED,
    ERR_INFO_CYCLE_LIMIT,
    ERR_INVALID_ELECTION_STATE,
    ERR_INVALID_REQUEST_STATE,
    ERR_SEGREGATION_OF_DUTIES,
)
from test_helpers.constants import (
    CATEGORY_CLOUD_STORAGE,
    CLOCK_EPOCH,
    DISPOSITION_ELECTED,
    DISPOSITION_EXECUTED,
    DISPOSITION_PENDING,
    DISPOSITION_PURGED,
    EL_ACTION_COUNTERSIGN,
    EL_ACTION_EXECUTE,
    EL_ACTION_REVERSE,
    EL_ACTION_SUBMIT,
    ELECTION_DELETE,
    ELECTION_DRAFT,
    ELECTION_EXECUTED,
    ELECTION_MEMORIALIZE,
    ELECTION_PENDING_COUNTERSIGN,
    ELECTION_REVERSED,
    ELECTION_SUBMITTED,
    MAX_INFO_CYCLES,
    PHASE_CLOSED,
    PHASE_DISCLOSURE,
    PHASE_WIND_DOWN,
    REQ_ACTION_DECIDE,
    REQ_ACTION_REQUEST_INFO,
    REQ_ACTION_RESUBMIT,
    REQ_ACTION_START_REVIEW,
    REQ_ACTION_SUBMIT,
    REQ_ACTION_WITHDRAW,
    REQUEST_INFO_REQUESTED,
    REQUEST_SUBMITTED,
    REQUEST_WITHDRAWN,
)

# The provider registered for these cases occupies a fourteen-day review window.
_REVIEW_WINDOW_DAYS = 14

# One clock position per pass of the information cycle, so that a window
# re-opened "from the current clock position" is visibly fresh each time.
_CYCLE_CLOCKS = (
    "2026-08-05T00:00:00Z",
    "2026-08-10T00:00:00Z",
    "2026-08-15T00:00:00Z",
)


def _instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC instant regardless of its fractional-digit width."""
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _transition_request(api, request_id, headers, action, **payload):
    return api.transition_platform_request(
        request_id, f.request_transition_payload(action, **payload), headers
    )


def _package_parked_after_three_info_cycles(api, case_number):
    """
    Build one CATALOG_ACCESS package that has completed three full information
    cycles and is parked in INFO_REQUESTED on a fourth request for paperwork.
    """
    fixtures.set_clock(api, CLOCK_EPOCH)
    platform = fixtures.register_platform(api, review_window_days=_REVIEW_WINDOW_DAYS)
    ctx = fixtures.authorized_estate(api, case_number)
    desk = make_platform_compliance_headers(platform["id"])
    request = fixtures.draft_request(api, ctx, platform["id"], platform["form_code"])
    fixtures.submit_request(api, ctx, request["id"])
    for cycle, clock in enumerate(_CYCLE_CLOCKS, start=1):
        get_success_data(_transition_request(api, request["id"], desk, REQ_ACTION_START_REVIEW))
        get_success_data(
            _transition_request(
                api,
                request["id"],
                desk,
                REQ_ACTION_REQUEST_INFO,
                missing_items=f"missing item batch {cycle}",
            )
        )
        fixtures.set_clock(api, clock)
        get_success_data(
            _transition_request(
                api,
                request["id"],
                ctx.fid_headers,
                REQ_ACTION_RESUBMIT,
                remediation_note=f"cycle {cycle} remediation",
            )
        )
    get_success_data(_transition_request(api, request["id"], desk, REQ_ACTION_START_REVIEW))
    get_success_data(
        _transition_request(
            api, request["id"], desk, REQ_ACTION_REQUEST_INFO, missing_items="fourth ask"
        )
    )
    return ctx, platform, request["id"]


def test_info_cycle_clears_the_window_and_reopens_it_at_the_new_clock(api):
    """
    Each pass of the information cycle takes the package out of the review
    window on the way to INFO_REQUESTED and puts it back at the clock position
    of the resubmission, raising the cycle count by exactly one each time.

    PRD: "A `Fiduciary` whose package sits in `INFO_REQUESTED` may resubmit it, advancing `INFO_REQUESTED → SUBMITTED`, storing a `remediation_note`, increasing `info_cycle_count` by exactly 1 and re-opening the window from the *current* clock position with a fresh `review_window_start` and `review_window_end`."

    Design: Difficulty/non_linear_state_machine/platform_request_info_cycle_loops_back_three_times_then_caps
    """
    fixtures.set_clock(api, CLOCK_EPOCH)
    platform = fixtures.register_platform(api, review_window_days=_REVIEW_WINDOW_DAYS)
    ctx = fixtures.authorized_estate(api, "PR-2737-F")
    desk = make_platform_compliance_headers(platform["id"])
    request = fixtures.draft_request(api, ctx, platform["id"], platform["form_code"])

    submitted = validate_success(
        _transition_request(api, request["id"], ctx.fid_headers, REQ_ACTION_SUBMIT), 200
    )
    assert submitted["status"] == REQUEST_SUBMITTED
    assert submitted["info_cycle_count"] == 0
    assert _instant(submitted["review_window_start"]) == _instant(CLOCK_EPOCH)
    assert _instant(submitted["review_window_end"]) == _instant(CLOCK_EPOCH) + timedelta(
        days=_REVIEW_WINDOW_DAYS
    )

    for cycle, clock in enumerate(_CYCLE_CLOCKS, start=1):
        validate_success(
            _transition_request(api, request["id"], desk, REQ_ACTION_START_REVIEW), 200
        )
        parked = validate_success(
            _transition_request(
                api,
                request["id"],
                desk,
                REQ_ACTION_REQUEST_INFO,
                missing_items=f"missing item batch {cycle}",
            ),
            200,
        )
        assert parked["status"] == REQUEST_INFO_REQUESTED
        assert parked["review_window_start"] is None
        assert parked["review_window_end"] is None

        fixtures.set_clock(api, clock)
        resubmitted = validate_success(
            _transition_request(
                api,
                request["id"],
                ctx.fid_headers,
                REQ_ACTION_RESUBMIT,
                remediation_note=f"cycle {cycle} remediation",
            ),
            200,
        )
        assert resubmitted["status"] == REQUEST_SUBMITTED
        assert resubmitted["info_cycle_count"] == cycle
        assert _instant(resubmitted["review_window_start"]) == _instant(clock)
        assert _instant(resubmitted["review_window_end"]) == _instant(clock) + timedelta(
            days=_REVIEW_WINDOW_DAYS
        )


def test_fourth_resubmission_is_capped_and_leaves_the_package_parked(api):
    """
    After three completed cycles the fourth resubmission is refused, and the
    refusal neither advances nor terminates the package: it stays in
    INFO_REQUESTED with its cycle count at three and no window occupied.

    PRD: "This closes the loop `UNDER_REVIEW → INFO_REQUESTED → SUBMITTED → UNDER_REVIEW`, and the loop is capped: resubmission is only permitted while `info_cycle_count` is strictly below three, so the third resubmission succeeds and raises the count from 2 to 3 while the fourth is rejected with `ERR_INFO_CYCLE_LIMIT`."

    Design: Difficulty/non_linear_state_machine/platform_request_info_cycle_loops_back_three_times_then_caps
    """
    ctx, _platform, request_id = _package_parked_after_three_info_cycles(api, "PR-2737-F2")

    refused = _transition_request(
        api,
        request_id,
        ctx.fid_headers,
        REQ_ACTION_RESUBMIT,
        remediation_note="cycle 4 remediation",
    )
    validate_error(refused, ERR_INFO_CYCLE_LIMIT)

    parked = fixtures.read_request(api, ctx, request_id)
    assert parked["status"] == REQUEST_INFO_REQUESTED
    assert parked["info_cycle_count"] == MAX_INFO_CYCLES
    assert parked["review_window_start"] is None
    assert parked["review_window_end"] is None


def test_decide_is_undefined_from_info_requested_and_withdrawal_is_terminal(api):
    """
    INFO_REQUESTED offers the provider's desk no decision edge, so a DECIDE is
    refused there; the fiduciary's withdrawal is accepted from the same node and
    is terminal, so a resubmission afterwards is refused in turn.

    PRD: "`APPROVED`, `DENIED` and `WITHDRAWN` are all terminal; any action submitted against a package whose current `status` does not define that action — deciding a package still in `SUBMITTED`, or submitting one already `APPROVED` — is rejected with `ERR_INVALID_REQUEST_STATE`."

    Design: Difficulty/non_linear_state_machine/platform_request_info_cycle_loops_back_three_times_then_caps
    """
    ctx, platform, request_id = _package_parked_after_three_info_cycles(api, "PR-2737-F3")
    desk = make_platform_compliance_headers(platform["id"])

    decided = _transition_request(api, request_id, desk, REQ_ACTION_DECIDE, decision="APPROVED")
    validate_error(decided, ERR_INVALID_REQUEST_STATE)

    withdrawn = validate_success(
        _transition_request(
            api,
            request_id,
            ctx.fid_headers,
            REQ_ACTION_WITHDRAW,
            withdrawal_reason="estate settled the account directly",
        ),
        200,
    )
    assert withdrawn["status"] == REQUEST_WITHDRAWN

    again = _transition_request(
        api,
        request_id,
        ctx.fid_headers,
        REQ_ACTION_RESUBMIT,
        remediation_note="one more try",
    )
    validate_error(again, ERR_INVALID_REQUEST_STATE)


def test_a_looping_package_never_produced_an_authority_grant(api):
    """
    Nothing in the information cycle grants authority: a package that has looped
    three times, been refused a fourth and then been withdrawn leaves no
    authority grant behind it at all.

    PRD: "An approval is the only event in the system that creates an **`AuthorityGrant`**."

    Design: Difficulty/non_linear_state_machine/platform_request_info_cycle_loops_back_three_times_then_caps
    """
    ctx, _platform, request_id = _package_parked_after_three_info_cycles(api, "PR-2737-F4")
    validate_error(
        _transition_request(
            api,
            request_id,
            ctx.fid_headers,
            REQ_ACTION_RESUBMIT,
            remediation_note="cycle 4 remediation",
        ),
        ERR_INFO_CYCLE_LIMIT,
    )
    validate_success(
        _transition_request(
            api,
            request_id,
            ctx.fid_headers,
            REQ_ACTION_WITHDRAW,
            withdrawal_reason="abandoned after four asks",
        ),
        200,
    )

    rows, meta = validate_paginated(
        api.list_authority_grants(ctx.fid_headers, platform_request_id=request_id)
    )
    assert meta["total_count"] == 0
    assert rows == []


def _two_fiduciary_estate_with_two_disclosed_assets(api, case_number):
    """
    One estate with two fiduciaries holding ISSUED letters and two cloud-storage
    accounts disclosed by a single approved catalogue request.
    """
    fixtures.set_clock(api, CLOCK_EPOCH)
    platform = fixtures.register_platform(api)
    ctx = fixtures.authorized_estate(api, case_number)
    second = fixtures.add_second_fiduciary(api, ctx, f"{case_number}-CO")
    memorial_asset = fixtures.add_asset(
        api,
        ctx,
        platform["id"],
        category=CATEGORY_CLOUD_STORAGE,
        account_handle="vault-photos",
        quoted_value_cents=120000,
    )
    delete_asset = fixtures.add_asset(
        api,
        ctx,
        platform["id"],
        category=CATEGORY_CLOUD_STORAGE,
        account_handle="vault-drafts",
        quoted_value_cents=60000,
    )
    fixtures.approved_request(api, ctx, platform["id"], platform["form_code"])
    return {
        "ctx": ctx,
        "platform": platform,
        "second_fiduciary_id": second["id"],
        "memorial_asset_id": memorial_asset["id"],
        "delete_asset_id": delete_asset["id"],
    }


def _pending_countersign_delete_election(api, case_number):
    """The same estate with a DELETE election awaiting its second signature."""
    env = _two_fiduciary_estate_with_two_disclosed_assets(api, case_number)
    env["delete_election"] = fixtures.draft_election(
        api,
        env["ctx"],
        env["delete_asset_id"],
        election=ELECTION_DELETE,
        election_note="purge drafts",
    )
    return env


def _countersigned_delete_election(api, case_number):
    env = _pending_countersign_delete_election(api, case_number)
    get_success_data(
        api.transition_disposition_election(
            env["delete_election"]["id"],
            f.election_transition_payload(
                EL_ACTION_COUNTERSIGN, attestation="second fiduciary concurs"
            ),
            make_fiduciary_headers(env["second_fiduciary_id"]),
        )
    )
    return env


def test_election_enters_the_machine_at_a_node_chosen_by_the_disposition(api):
    """
    Two elections filed through the same endpoint on the same estate open at
    different initial states: the memorialization at DRAFT and the deletion one
    node earlier, waiting for a second fiduciary.

    PRD: "A `DELETE` election opens at `PENDING_COUNTERSIGN`, because deletion destroys an account permanently and one fiduciary acting alone may not order it."

    Design: Difficulty/non_linear_state_machine/delete_election_detours_through_countersign_and_purged_refuses_reverse
    """
    env = _two_fiduciary_estate_with_two_disclosed_assets(api, "PR-2737-G")
    ctx = env["ctx"]

    memorial = validate_success(
        api.create_disposition_election(
            env["memorial_asset_id"],
            f.election_payload(
                fixtures.asset_version(api, ctx, env["memorial_asset_id"]),
                election=ELECTION_MEMORIALIZE,
                election_note="memorial page",
            ),
            ctx.fid_headers,
        ),
        201,
    )
    deletion = validate_success(
        api.create_disposition_election(
            env["delete_asset_id"],
            f.election_payload(
                fixtures.asset_version(api, ctx, env["delete_asset_id"]),
                election=ELECTION_DELETE,
                election_note="purge drafts",
            ),
            ctx.fid_headers,
        ),
        201,
    )

    assert memorial["status"] == ELECTION_DRAFT
    assert deletion["status"] == ELECTION_PENDING_COUNTERSIGN
    assert deletion["elected_by_fiduciary_id"] == ctx.fiduciary_id
    assert deletion["countersigned_by_fiduciary_id"] is None
    assert memorial["countersigned_by_fiduciary_id"] is None


def test_submit_is_undefined_while_the_deletion_awaits_its_countersignature(api):
    """
    PENDING_COUNTERSIGN is an extra node on the deletion branch, not a synonym
    for DRAFT, so a submission attempted there is refused on the entity-state
    band and the election does not move.

    PRD: "Estate closure first (`ERR_ESTATE_CLOSED`, 409), then whether the target record is in a state from which the submitted action is defined, per entity in this order: document (`ERR_INVALID_DOCUMENT_STATE`), platform request (`ERR_INVALID_REQUEST_STATE`), authority grant (`ERR_INVALID_GRANT_STATE`), disposition election (`ERR_INVALID_ELECTION_STATE`), cancellation order (`ERR_INVALID_ORDER_STATE`), refund claim (`ERR_INVALID_CLAIM_STATE`), valuation run (`ERR_INVALID_RUN_STATE`) — all HTTP 409 — and lastly the once-per-estate finalization guard (`ERR_VALUATION_ALREADY_FINALIZED`, 409)."

    Design: Difficulty/non_linear_state_machine/delete_election_detours_through_countersign_and_purged_refuses_reverse
    """
    env = _pending_countersign_delete_election(api, "PR-2737-G2")
    ctx = env["ctx"]

    refused = api.transition_disposition_election(
        env["delete_election"]["id"],
        f.election_transition_payload(EL_ACTION_SUBMIT),
        ctx.fid_headers,
    )
    validate_error(refused, ERR_INVALID_ELECTION_STATE)

    election = fixtures.read_election(api, ctx, env["delete_election"]["id"])
    assert election["status"] == ELECTION_PENDING_COUNTERSIGN
    asset = fixtures.read_asset(api, ctx, env["delete_asset_id"])
    assert asset["disposition_status"] == DISPOSITION_PENDING


def test_the_electing_fiduciary_may_not_countersign_its_own_deletion(api):
    """
    The detour exists to force two hands onto an irreversible deletion, so the
    fiduciary who elected it is refused its own countersignature.

    PRD: "The countersigner must belong to the account's estate and must hold `letters_status` of `ISSUED`, and the `X-User-ID` they present must differ from the election's `elected_by_fiduciary_id`; a fiduciary countersigning their own deletion is refused with `ERR_SEGREGATION_OF_DUTIES` at HTTP 403, and it is that code rather than a generic permission error because the caller does hold the right role."

    Design: Difficulty/non_linear_state_machine/delete_election_detours_through_countersign_and_purged_refuses_reverse
    """
    env = _pending_countersign_delete_election(api, "PR-2737-G3")
    ctx = env["ctx"]

    refused = api.transition_disposition_election(
        env["delete_election"]["id"],
        f.election_transition_payload(
            EL_ACTION_COUNTERSIGN, attestation="self-countersign attempt"
        ),
        ctx.fid_headers,
    )
    validate_error(refused, ERR_SEGREGATION_OF_DUTIES)

    election = fixtures.read_election(api, ctx, env["delete_election"]["id"])
    assert election["status"] == ELECTION_PENDING_COUNTERSIGN
    assert election["countersigned_by_fiduciary_id"] is None


def test_a_co_fiduciary_countersignature_joins_the_two_branches_at_draft(api):
    """
    The second fiduciary's countersignature moves the deletion onto the node the
    memorialization started from, recording who signed and what they attested.

    PRD: "A `PENDING_COUNTERSIGN` election is countersigned by a `Fiduciary`, advancing it to `DRAFT` where the two branches join."

    Design: Difficulty/non_linear_state_machine/delete_election_detours_through_countersign_and_purged_refuses_reverse
    """
    env = _pending_countersign_delete_election(api, "PR-2737-G4")
    ctx = env["ctx"]

    countersigned = validate_success(
        api.transition_disposition_election(
            env["delete_election"]["id"],
            f.election_transition_payload(
                EL_ACTION_COUNTERSIGN, attestation="second fiduciary concurs"
            ),
            make_fiduciary_headers(env["second_fiduciary_id"]),
        ),
        200,
    )

    assert countersigned["status"] == ELECTION_DRAFT
    assert countersigned["countersigned_by_fiduciary_id"] == env["second_fiduciary_id"]
    assert countersigned["attestation"] == "second fiduciary concurs"
    assert countersigned["elected_by_fiduciary_id"] == ctx.fiduciary_id


def test_submission_from_the_joined_node_marks_the_account_elected(api):
    """
    Once the deletion has joined the memorialization's branch at DRAFT, the
    ordinary submission edge is available and drives the account's independent
    disposition dimension forward.

    PRD: "Submission sets the account's `disposition_status` to `ELECTED`, recomputes the estate's disposition counters and re-derives the phase."

    Design: Difficulty/non_linear_state_machine/delete_election_detours_through_countersign_and_purged_refuses_reverse
    """
    env = _countersigned_delete_election(api, "PR-2737-G5")
    ctx = env["ctx"]

    submitted = validate_success(
        api.transition_disposition_election(
            env["delete_election"]["id"],
            f.election_transition_payload(EL_ACTION_SUBMIT),
            ctx.fid_headers,
        ),
        200,
    )
    assert submitted["status"] == ELECTION_SUBMITTED

    asset = fixtures.read_asset(api, ctx, env["delete_asset_id"])
    assert asset["disposition_status"] == DISPOSITION_ELECTED


def test_executing_a_deletion_lands_the_account_on_purged_and_keeps_its_handle(api):
    """
    The deletion branch ends on a different node from the memorialization branch:
    the account is purged rather than merely executed, and the handle of the
    destroyed account survives on the record.

    PRD: "A `DELETE` execution sets the account's `disposition_status` to the terminal `PURGED` and stamps `disposed_at`."

    Design: Difficulty/non_linear_state_machine/delete_election_detours_through_countersign_and_purged_refuses_reverse
    """
    env = _countersigned_delete_election(api, "PR-2737-G6")
    ctx = env["ctx"]
    get_success_data(
        api.transition_disposition_election(
            env["delete_election"]["id"],
            f.election_transition_payload(EL_ACTION_SUBMIT),
            ctx.fid_headers,
        )
    )

    executed = validate_success(
        api.transition_disposition_election(
            env["delete_election"]["id"],
            f.election_transition_payload(
                EL_ACTION_EXECUTE, platform_confirmation_reference="CV-PURGE-1"
            ),
            make_platform_compliance_headers(env["platform"]["id"]),
        ),
        200,
    )
    assert executed["status"] == ELECTION_EXECUTED

    asset = fixtures.read_asset(api, ctx, env["delete_asset_id"])
    assert asset["disposition_status"] == DISPOSITION_PURGED
    assert asset["disposed_at"] is not None
    assert asset["account_handle"] == "vault-drafts"


def test_purged_is_the_one_posture_with_no_reverse_edge(api):
    """
    The reversal that the memorialization branch accepts is refused for a purged
    account, and the refusal leaves the account purged.

    PRD: "Reversal requires the account's `disposition_status` to be `EXECUTED`; a `PURGED` account can never be reversed, because a deleted account cannot be brought back, and the attempt is refused with `ERR_INVALID_ELECTION_STATE`."

    Design: Difficulty/non_linear_state_machine/delete_election_detours_through_countersign_and_purged_refuses_reverse
    """
    env = _countersigned_delete_election(api, "PR-2737-G7")
    ctx = env["ctx"]
    desk = make_platform_compliance_headers(env["platform"]["id"])
    get_success_data(
        api.transition_disposition_election(
            env["delete_election"]["id"],
            f.election_transition_payload(EL_ACTION_SUBMIT),
            ctx.fid_headers,
        )
    )
    get_success_data(
        api.transition_disposition_election(
            env["delete_election"]["id"],
            f.election_transition_payload(
                EL_ACTION_EXECUTE, platform_confirmation_reference="CV-PURGE-1"
            ),
            desk,
        )
    )

    refused = api.transition_disposition_election(
        env["delete_election"]["id"],
        f.election_transition_payload(EL_ACTION_REVERSE, reason="family objection"),
        desk,
    )
    validate_error(refused, ERR_INVALID_ELECTION_STATE)

    election = fixtures.read_election(api, ctx, env["delete_election"]["id"])
    assert election["status"] == ELECTION_EXECUTED
    asset = fixtures.read_asset(api, ctx, env["delete_asset_id"])
    assert asset["disposition_status"] == DISPOSITION_PURGED


def test_the_memorialize_branch_submits_straight_from_draft(api):
    """
    The extra node belongs to the deletion alone: a memorialization filed on the
    same estate is submitted from DRAFT with nobody countersigning it.

    PRD: "Submission advances the election `DRAFT → SUBMITTED` and is a `Fiduciary` action."

    Design: Difficulty/non_linear_state_machine/delete_election_detours_through_countersign_and_purged_refuses_reverse
    """
    env = _two_fiduciary_estate_with_two_disclosed_assets(api, "PR-2737-G8")
    ctx = env["ctx"]
    election = fixtures.draft_election(
        api,
        ctx,
        env["memorial_asset_id"],
        election=ELECTION_MEMORIALIZE,
        election_note="memorial page",
    )
    assert election["status"] == ELECTION_DRAFT

    submitted = validate_success(
        api.transition_disposition_election(
            election["id"],
            f.election_transition_payload(EL_ACTION_SUBMIT),
            ctx.fid_headers,
        ),
        200,
    )
    assert submitted["status"] == ELECTION_SUBMITTED
    assert submitted["countersigned_by_fiduciary_id"] is None


def _estate_at_disclosure_with_submitted_memorialization(api, case_number):
    """
    One estate holding a single disclosed cloud-storage account with a
    memorialization already submitted against it, so the estate's phase sits at
    DISCLOSURE with one account still pending disposition.
    """
    fixtures.set_clock(api, CLOCK_EPOCH)
    platform = fixtures.register_platform(api, supports_deletion=False)
    ctx = fixtures.authorized_estate(api, case_number)
    asset = fixtures.add_asset(
        api,
        ctx,
        platform["id"],
        category=CATEGORY_CLOUD_STORAGE,
        account_handle="vault-only",
        quoted_value_cents=200000,
    )
    fixtures.approved_request(api, ctx, platform["id"], platform["form_code"])
    election = fixtures.submitted_election(
        api,
        ctx,
        asset["id"],
        election=ELECTION_MEMORIALIZE,
        election_note="memorialize the vault",
    )
    return {
        "ctx": ctx,
        "platform": platform,
        "asset_id": asset["id"],
        "election_id": election["id"],
        "desk": make_platform_compliance_headers(platform["id"]),
    }


def _estate_closed_after_the_phase_walk(api, case_number):
    """Walk the phase forward, back and forward again, then close the estate."""
    env = _estate_at_disclosure_with_submitted_memorialization(api, case_number)
    ctx, desk = env["ctx"], env["desk"]
    get_success_data(
        api.transition_disposition_election(
            env["election_id"],
            f.election_transition_payload(
                EL_ACTION_EXECUTE, platform_confirmation_reference="CV-MEM-1"
            ),
            desk,
        )
    )
    get_success_data(
        api.transition_disposition_election(
            env["election_id"],
            f.election_transition_payload(
                EL_ACTION_REVERSE, reason="heir contested the memorial page"
            ),
            desk,
        )
    )
    second = fixtures.submitted_election(
        api,
        ctx,
        env["asset_id"],
        election=ELECTION_MEMORIALIZE,
        election_note="second attempt",
    )
    get_success_data(
        api.transition_disposition_election(
            second["id"],
            f.election_transition_payload(
                EL_ACTION_EXECUTE, platform_confirmation_reference="CV-MEM-2"
            ),
            desk,
        )
    )
    env["second_election_id"] = second["id"]
    env["phase_after_second_execute"] = fixtures.read_estate(api, ctx)["administration_phase"]
    fixtures.add_beneficiary(api, ctx)
    fixtures.finalized_valuation_run(api, ctx, finalization_note="inventory complete")
    env["closed"] = get_success_data(
        api.close_estate(
            ctx.estate_id,
            f.close_estate_payload(closing_statement="all digital assets memorialized"),
            ctx.fid_headers,
        )
    )
    return env


def test_the_last_disposition_walks_the_phase_forward_into_wind_down(api):
    """
    The phase is derived, not stored: executing the only outstanding disposition
    makes the disposed count meet the inventory total and the estate moves on.

    PRD: "`DISCLOSURE → WIND_DOWN` follows the disposition that makes `assets_disposed_count` equal `inventory_total_count`, with at least one asset in inventory."

    Design: Difficulty/non_linear_state_machine/estate_phase_walks_back_from_wind_down_to_disclosure_then_pins_at_closed
    """
    env = _estate_at_disclosure_with_submitted_memorialization(api, "PR-2737-H")
    ctx = env["ctx"]

    before = fixtures.read_estate(api, ctx)
    assert before["administration_phase"] == PHASE_DISCLOSURE
    assert before["inventory_total_count"] == 1
    assert before["assets_disposed_count"] == 0
    assert before["assets_pending_disposition_count"] == 1

    validate_success(
        api.transition_disposition_election(
            env["election_id"],
            f.election_transition_payload(
                EL_ACTION_EXECUTE, platform_confirmation_reference="CV-MEM-1"
            ),
            env["desk"],
        ),
        200,
    )

    after = fixtures.read_estate(api, ctx)
    assert after["administration_phase"] == PHASE_WIND_DOWN
    assert after["assets_disposed_count"] == 1
    assert after["assets_pending_disposition_count"] == 0
    assert after["inventory_total_count"] == 1


def test_a_reversal_walks_the_phase_back_out_of_wind_down(api):
    """
    The same derivation runs backwards: reversing the execution returns the
    account to PENDING and the estate to the phase it had left.

    PRD: "The reverse edges are equally real: a reversal or rejection that returns an account to `PENDING` drops the estate back `WIND_DOWN → DISCLOSURE`, and an authority collapse walks it back `AUTHORIZED → INTAKE` or `DISCLOSURE → INTAKE` as soon as no fiduciary holds issued letters."

    Design: Difficulty/non_linear_state_machine/estate_phase_walks_back_from_wind_down_to_disclosure_then_pins_at_closed
    """
    env = _estate_at_disclosure_with_submitted_memorialization(api, "PR-2737-H2")
    ctx, desk = env["ctx"], env["desk"]
    get_success_data(
        api.transition_disposition_election(
            env["election_id"],
            f.election_transition_payload(
                EL_ACTION_EXECUTE, platform_confirmation_reference="CV-MEM-1"
            ),
            desk,
        )
    )
    assert fixtures.read_estate(api, ctx)["administration_phase"] == PHASE_WIND_DOWN

    reversed_election = validate_success(
        api.transition_disposition_election(
            env["election_id"],
            f.election_transition_payload(
                EL_ACTION_REVERSE, reason="heir contested the memorial page"
            ),
            desk,
        ),
        200,
    )
    assert reversed_election["status"] == ELECTION_REVERSED

    estate = fixtures.read_estate(api, ctx)
    assert estate["administration_phase"] == PHASE_DISCLOSURE
    assert estate["assets_disposed_count"] == 0
    assert estate["assets_pending_disposition_count"] == 1

    asset = fixtures.read_asset(api, ctx, env["asset_id"])
    assert asset["disposition_status"] == DISPOSITION_PENDING
    assert asset["disposed_at"] is None


def test_re_execution_walks_the_phase_forward_again_and_closure_pins_it(api):
    """
    A second memorialization drives the phase back into WIND_DOWN, and closing
    the estate replaces the derivation with a fixed terminal phase.

    PRD: "Closure stamps `closed_at`, stores the `closing_statement` and pins `administration_phase` to `CLOSED`, suppressing all further derivation."

    Design: Difficulty/non_linear_state_machine/estate_phase_walks_back_from_wind_down_to_disclosure_then_pins_at_closed
    """
    env = _estate_closed_after_the_phase_walk(api, "PR-2737-H3")
    ctx = env["ctx"]

    assert env["phase_after_second_execute"] == PHASE_WIND_DOWN
    assert env["closed"]["administration_phase"] == PHASE_CLOSED
    assert env["closed"]["closed_at"] is not None
    assert env["closed"]["closing_statement"] == "all digital assets memorialized"

    estate = fixtures.read_estate(api, ctx)
    assert estate["administration_phase"] == PHASE_CLOSED
    assert estate["inventory_total_count"] == 1
    assert estate["assets_disposed_count"] == 1
    assert estate["assets_pending_disposition_count"] == 0
    assert fixtures.read_asset(api, ctx, env["asset_id"])["disposition_status"] == (
        DISPOSITION_EXECUTED
    )


def test_after_closure_writes_are_refused_instead_of_re_deriving_the_phase(api):
    """
    Once the phase is pinned, neither a new account nor a reversal of the
    execution that produced the pin is allowed to move it: both are refused, and
    reads still answer.

    PRD: "From that moment every mutating operation anywhere beneath the estate is refused with `ERR_ESTATE_CLOSED`, including a second attempt to close it, while reads continue to work so the file remains auditable forever."

    Design: Difficulty/non_linear_state_machine/estate_phase_walks_back_from_wind_down_to_disclosure_then_pins_at_closed
    """
    env = _estate_closed_after_the_phase_walk(api, "PR-2737-H4")
    ctx = env["ctx"]

    late_asset = api.create_digital_asset(
        ctx.estate_id,
        f.digital_asset_payload(
            env["platform"]["id"],
            category=CATEGORY_CLOUD_STORAGE,
            account_handle="vault-late",
            quoted_value_cents=1000,
        ),
        ctx.fid_headers,
    )
    validate_error(late_asset, ERR_ESTATE_CLOSED)

    late_reverse = api.transition_disposition_election(
        env["second_election_id"],
        f.election_transition_payload(EL_ACTION_REVERSE, reason="too late"),
        env["desk"],
    )
    validate_error(late_reverse, ERR_ESTATE_CLOSED)

    second_close = api.close_estate(
        ctx.estate_id,
        f.close_estate_payload(closing_statement="closing once more"),
        ctx.fid_headers,
    )
    validate_error(second_close, ERR_ESTATE_CLOSED)

    estate = fixtures.read_estate(api, ctx)
    assert estate["administration_phase"] == PHASE_CLOSED
    assert estate["inventory_total_count"] == 1
