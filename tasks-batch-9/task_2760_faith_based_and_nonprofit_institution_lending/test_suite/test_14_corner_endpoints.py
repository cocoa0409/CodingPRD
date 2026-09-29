"""
Queue B — §1.9 section ``endpoints``.

The four endpoint behaviours that a per-endpoint reading of §4 alone would not
pin down: the computed underwriting read that must recompute without mutating,
the draw-request collection's declared filters and ordering, the collateral
assignment observed from both ends of its foreign key, and the three-way answer
of the construction-completion act.
"""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
)

from test_helpers.api_errors import (
    ERR_DRAW_INVALID_STATE,
    ERR_INVALID_REQUEST,
    ERR_LOAN_NOT_IN_DRAW_PHASE,
)
from test_helpers.assertions import (
    assert_commitment_conservation,
    assert_fields,
    assert_id_order,
    assert_iso_equal,
    assert_loan_ledger,
    assert_nulls,
    assert_pagination_meta,
    assert_ratio,
)
from test_helpers.factories import (
    construction_completion_payload,
    draw_rejection_payload,
    draw_request_payload,
    release_payload,
)
from test_helpers.fixtures import (
    build_approved_draw,
    build_draw_request,
    chain_through_assignment,
    chain_through_loan,
    reset_clock,
)
from test_helpers.test_users import (
    COMMITTEE_MEMBER,
    CREDIT_ANALYST,
    LOAN_SERVICER,
)

# The recipes for this section file no endowment figure, so the key is dropped
# and the endpoint's own default stands.
BORROWER = {"endowment_market_value_cents": None}


def test_the_underwriting_summary_recomputes_every_cap_without_touching_the_application(api):
    """
    A 100000000 request against a 400000000-worth sanctuary and a resolution
    authorising only 100000000: the computed read names AUTHORIZED_AMOUNT as the
    binding cap, answers identically when BLENDED is asked for over a window that
    is entirely audited, and leaves the application's own snapshot fields — which
    only the referral fills — still null at the version it started from.

    PRD §3.5: "A computed read exposes the whole underwriting picture without mutating the application, and is available to `PlatformAdmin`, `CreditAnalyst`, `CreditCommitteeMember` and the borrower's `InstitutionRepresentative`."
    PRD §3.5: "It answers with `giving_basis` echoing the applied choice, `period_count` and `audited_period_count` from the institution, `window_period_labels` — the four `period_label` values of the window in `period_end` descending order — `giving_base_cents` and `net_available_dollars` recomputed under the applied basis, `membership_trend_pct` to four decimal places, `collateral_lending_value_cents` summed over first-lien assigned assets, `max_supportable_principal_cents`, `requested_amount_cents`, and `binding_cap`, which names which cap produced the minimum as one of `DEBT_SERVICE`, `COLLATERAL`, `BYLAWS_CAP`, `AUTHORIZED_AMOUNT` or `PLEDGE_ADVANCE_LTV`."
    PRD §3.1: "Under `AUDITED_ONLY`, each period contributes its full `unrestricted_contributions_cents` and no haircut applies."
    PRD §3.5: "The **authorised-amount cap** is the governance packet's `authorized_amount_cents`."
    PRD §3.5: "The maximum supportable principal is the lowest of the caps in force."
    PRD §3.5: "A new application opens in `DRAFT` with `revision_count` at 0 and every snapshot and audit field null: `giving_basis`, `giving_base_cents`, `net_available_dollars`, `collateral_lending_value_cents`, `max_supportable_principal_cents`, `prepared_by_user_id`, `decided_by_user_id` and `revision_reason`."

    Design: Corner/endpoints/underwriting_summary_recomputes_the_basis_without_mutating_the_application
    """
    reset_clock(api)
    chain = chain_through_assignment(
        api,
        institution_overrides=BORROWER,
        authorization_overrides={"authorized_amount_cents": 100000000},
        application_overrides={
            "requested_amount_cents": 100000000,
            "term_months": 240,
        },
    )
    before = chain.read_application()
    version_before = before["version"]
    assert_fields(before, status="UNDERWRITING", requested_amount_cents=100000000)

    summary = get_success_data(
        api.get_underwriting_summary(chain.loan_application_id, CREDIT_ANALYST)
    )

    # The window is entirely audited, so the mandated basis is AUDITED_ONLY and
    # the four unrestricted figures 50000000 + 52000000 + 50000000 + 55000000
    # give a 207000000 base. Net available is the per-period-then-sum order:
    # 100001 + 110001 + 90001 + 131998 == 432001 whole dollars.
    assert_fields(
        summary,
        giving_basis="AUDITED_ONLY",
        period_count=4,
        audited_period_count=4,
        giving_base_cents=207000000,
        net_available_dollars=432001,
        requested_amount_cents=100000000,
    )
    assert summary["window_period_labels"] == ["2025Q4", "2025Q3", "2025Q2", "2025Q1"]
    # 520 households against the oldest period's 500 is a 0.0400 trend.
    assert_ratio(summary["membership_trend_pct"], 0.0400, "membership_trend_pct")
    # floor(500000000 x 50%) x 1.00 first-lien factor x 90% seasoning haircut.
    assert summary["collateral_lending_value_cents"] == 225000000
    # DEBT_SERVICE floor(432001 / 1.2000) == 360000 dollars x 8.5 x 100 ==
    # 306000000; COLLATERAL 225000000; BYLAWS_CAP 500000000; AUTHORIZED_AMOUNT
    # 100000000 is the unique minimum.
    assert_fields(
        summary,
        max_supportable_principal_cents=100000000,
        binding_cap="AUTHORIZED_AMOUNT",
    )

    blended = get_success_data(
        api.get_underwriting_summary(
            chain.loan_application_id, COMMITTEE_MEMBER, {"giving_basis": "BLENDED"}
        )
    )
    # The applied choice is echoed, but every audited period contributes its full
    # figure under either basis, so no computed number moves.
    assert_fields(
        blended,
        giving_basis="BLENDED",
        period_count=4,
        audited_period_count=4,
        giving_base_cents=207000000,
        net_available_dollars=432001,
        collateral_lending_value_cents=225000000,
        max_supportable_principal_cents=100000000,
        binding_cap="AUTHORIZED_AMOUNT",
    )
    assert blended["window_period_labels"] == ["2025Q4", "2025Q3", "2025Q2", "2025Q1"]

    after = chain.read_application()
    assert after["version"] == version_before, (
        "the computed read must not advance the application's version"
    )
    assert_iso_equal(after["updated_at"], before["updated_at"], "updated_at")
    assert_fields(after, status="UNDERWRITING", giving_basis="AUDITED_ONLY")
    assert_nulls(after, "collateral_lending_value_cents", "max_supportable_principal_cents")


def test_the_draw_collection_filters_by_status_and_phase_inside_created_at_order(api):
    """
    Three draws on one loan in three different states: the unfiltered list returns
    all three oldest-first under the default limit of 10, each declared filter
    narrows total_count to the single matching row, and a window of two rows taken
    from offset 1 reports the unwindowed total with nothing left beyond it.

    PRD §2.3: "`limit` caps the number of records returned; it defaults to 10 when omitted, may not be smaller than 1, and may not exceed 100."
    PRD §2.3: "List responses report `limit`, `offset`, `total_count` and `has_more` inside the `meta` object of the envelope, where `total_count` is the size of the full filtered result set before the page window is applied and `has_more` indicates whether any record remains beyond the current window."
    PRD §2.3: "Pledges, draw requests, covenants and workout plans use the plain `created_at` ascending default."
    PRD §2.3: "Draw requests accept `loan_id`, `status` and `project_phase`."
    PRD §3.7: "A new request opens in `SUBMITTED` with `approved_amount_cents`, `inspector_note`, `void_reason` and every waterfall figure null."
    PRD §3.7: "On success the draw moves `SUBMITTED → APPROVED`, `approved_amount_cents` and `inspector_note` are stored, the loan's `reserved_draw_cents` rises by the approved amount, and `version` advances by 1 on the draw and by 1 on the loan."
    PRD §3.7: "Rejection is the sibling arm: on a `SUBMITTED` draw it stores the submitted `inspector_note`, moves the draw `SUBMITTED → REJECTED`, advances the draw's `version` by 1, and leaves every ledger figure on the loan untouched."

    Design: Corner/endpoints/draw_request_list_filters_by_loan_status_and_phase_in_created_at_order
    """
    reset_clock(api)
    chain = chain_through_loan(api, institution_overrides=BORROWER)

    submitted = build_draw_request(
        api,
        chain.loan_id,
        project_phase="SITE_WORK",
        requested_amount_cents=100000,
        percent_complete=0.0500,
    )
    approved = build_approved_draw(
        api,
        chain.loan_id,
        200000,
        project_phase="FOUNDATION",
        requested_amount_cents=200000,
        percent_complete=0.1000,
    )
    third = build_draw_request(
        api,
        chain.loan_id,
        project_phase="SHELL",
        requested_amount_cents=300000,
        percent_complete=0.2000,
    )
    rejected = get_success_data(
        api.reject_draw_request(third["id"], draw_rejection_payload(), LOAN_SERVICER)
    )
    assert rejected["status"] == "REJECTED"

    rows, meta = validate_paginated(
        api.list_draw_requests(CREDIT_ANALYST, {"loan_id": chain.loan_id})
    )
    assert_pagination_meta(meta, total_count=3, limit=10, offset=0, has_more=False)
    assert_id_order(rows, [submitted["id"], approved["id"], third["id"]])
    assert_fields(rows[0], status="SUBMITTED", project_phase="SITE_WORK")
    assert_nulls(rows[0], "approved_amount_cents")
    assert_fields(
        rows[1],
        status="APPROVED",
        project_phase="FOUNDATION",
        approved_amount_cents=200000,
    )
    assert_fields(rows[2], status="REJECTED", project_phase="SHELL")
    assert_nulls(rows[2], "approved_amount_cents")

    by_status, status_meta = validate_paginated(
        api.list_draw_requests(
            CREDIT_ANALYST, {"loan_id": chain.loan_id, "status": "APPROVED"}
        )
    )
    assert_pagination_meta(status_meta, total_count=1, has_more=False)
    assert_id_order(by_status, [approved["id"]])

    by_phase, phase_meta = validate_paginated(
        api.list_draw_requests(
            CREDIT_ANALYST, {"loan_id": chain.loan_id, "project_phase": "SHELL"}
        )
    )
    assert_pagination_meta(phase_meta, total_count=1, has_more=False)
    assert_id_order(by_phase, [third["id"]])
    assert by_phase[0]["project_phase"] == "SHELL"

    window, window_meta = validate_paginated(
        api.list_draw_requests(
            CREDIT_ANALYST, {"loan_id": chain.loan_id, "limit": 2, "offset": 1}
        )
    )
    assert_pagination_meta(window_meta, total_count=3, limit=2, offset=1, has_more=False)
    assert_id_order(window, [approved["id"], third["id"]])

    # Only the approved draw reserves; the rejected one moved no ledger figure.
    assert_loan_ledger(
        chain.read_loan(),
        reserved_draw_cents=200000,
        disbursed_principal_cents=0,
        undrawn_commitment_cents=225000000,
    )


def test_an_occupied_asset_is_reachable_from_both_ends_and_the_reverse_filter_empties_on_release(api):
    """
    While the sanctuary is pledged, the reverse filter on the application finds it
    and the packet's filter finds the application; the moment the lien is released
    the reverse filter returns nothing, yet the asset stays discoverable through
    its institution with the ended occupation preserved in lien_history.

    PRD §2.4: "There is no nesting in the URL hierarchy: a child records its parent as a foreign key in its own request body rather than living beneath the parent's path, and every foreign key is reachable in the reverse direction through the corresponding filtered list."
    PRD §2.3: "Collateral assets accept `institution_id`, `assigned_loan_application_id` and `asset_type`."
    PRD §2.3: "Loan applications accept `institution_id`, `governance_authorization_id`, `pledge_campaign_id`, `status` and `purpose`."
    PRD §3.4: "The release appends the occupation just ended to `lien_history` as a record carrying `loan_application_id`, `lien_position`, `effective_from`, `effective_to` and `released_at`, with the list held in ascending `released_at` order and never rewritten once appended."
    PRD §3.4: "The four current-occupation fields are cleared to null, the asset is re-valued at the first-lien factor, `lending_value_cents` is rewritten, and `version` advances by 1."

    Design: Corner/endpoints/collateral_assignment_is_reachable_from_both_ends_and_empties_on_release
    """
    reset_clock(api)
    chain = chain_through_assignment(api, institution_overrides=BORROWER)

    occupied, occupied_meta = validate_paginated(
        api.list_collateral_assets(
            COMMITTEE_MEMBER, {"assigned_loan_application_id": chain.loan_application_id}
        )
    )
    assert_pagination_meta(occupied_meta, total_count=1, has_more=False)
    assert_id_order(occupied, [chain.collateral_asset_id])
    assert_fields(occupied[0], lien_position=1, lending_value_cents=225000000)
    assert_iso_equal(
        occupied[0]["lien_effective_from"], "2026-08-01T00:00:00Z", "lien_effective_from"
    )

    applications, application_meta = validate_paginated(
        api.list_loan_applications(
            COMMITTEE_MEMBER,
            {
                "governance_authorization_id": chain.governance_authorization_id,
                "status": "UNDERWRITING",
            },
        )
    )
    assert_pagination_meta(application_meta, total_count=1, has_more=False)
    assert_id_order(applications, [chain.loan_application_id])

    released = get_success_data(
        api.release_collateral_asset(
            chain.collateral_asset_id, release_payload(), CREDIT_ANALYST
        )
    )
    assert_nulls(
        released,
        "assigned_loan_application_id",
        "lien_position",
        "lien_effective_from",
        "lien_effective_to",
    )
    assert len(released["lien_history"]) == 1, (
        f"expected one lien_history entry, got {released['lien_history']!r}"
    )
    record = released["lien_history"][0]
    assert record["loan_application_id"] == chain.loan_application_id
    assert record["lien_position"] == 1
    assert_iso_equal(record["effective_from"], "2026-08-01T00:00:00Z", "effective_from")
    assert_iso_equal(record["effective_to"], "2031-08-01T00:00:00Z", "effective_to")
    assert record["released_at"] is not None, "released_at must be recorded"

    empty, empty_meta = validate_paginated(
        api.list_collateral_assets(
            COMMITTEE_MEMBER, {"assigned_loan_application_id": chain.loan_application_id}
        )
    )
    assert_pagination_meta(empty_meta, total_count=0, has_more=False)
    assert empty == [], f"the reverse filter must go empty on release, got {empty!r}"

    by_institution, institution_meta = validate_paginated(
        api.list_collateral_assets(
            COMMITTEE_MEMBER,
            {"institution_id": chain.institution_id, "asset_type": "SANCTUARY"},
        )
    )
    assert_pagination_meta(institution_meta, total_count=1, has_more=False)
    assert_id_order(by_institution, [chain.collateral_asset_id])
    # Re-valued at the first-lien factor: the released asset is worth what an
    # unassigned one is worth.
    assert by_institution[0]["lending_value_cents"] == 225000000


def test_construction_completion_answers_three_ways_and_then_closes_the_draw_phase(api):
    """
    The same completion call on one loan: the false inspection flag is a schema
    refusal, the true flag is blocked while a SUBMITTED draw is still open, and
    once that draw is rejected it succeeds — cancelling the whole undrawn
    commitment and shutting the door on any further draw.

    PRD §3.7: "Construction closes out through a `LoanServicer` act that requires `final_inspection_passed` to be present and true — a completion submitted with it false is refused with `ERR_INVALID_REQUEST` — and accepts an optional `completion_note`."
    PRD §3.7: "No draw on the loan may still be open: if any sits in `SUBMITTED`, `APPROVED` or `SUSPENDED` the completion is refused with `ERR_DRAW_INVALID_STATE`."
    PRD §3.7: "The act is available from either draw-phase state and lands in the same place in both cases: `PENDING_FIRST_DRAW → AMORTIZING` for a loan that never drew, and `CONSTRUCTION_DRAW → AMORTIZING` for one that did."
    PRD §3.7: "Both variants perform the same two ledger movements — the whole of `undrawn_commitment_cents` moves into `cancelled_commitment_cents` and `undrawn_commitment_cents` is set to 0, and the whole of `retainage_held_cents` moves into `retainage_released_cents` and `retainage_held_cents` is set to 0 — and both advance `version` by 1."
    PRD §3.7: "A request against a loan whose `servicing_status` is `AMORTIZING` or `PAID_OFF` is refused with `ERR_LOAN_NOT_IN_DRAW_PHASE`."
    PRD §2.11: "the sum of `disbursed_principal_cents`, `undrawn_commitment_cents` and `cancelled_commitment_cents` must always equal `principal_cents`."

    Design: Corner/endpoints/construction_completion_is_gated_on_the_inspection_flag_and_open_draws
    """
    reset_clock(api)
    chain = chain_through_loan(api, institution_overrides=BORROWER)
    draw = build_draw_request(
        api,
        chain.loan_id,
        project_phase="SITE_WORK",
        requested_amount_cents=100000,
        percent_complete=0.0500,
    )
    assert draw["status"] == "SUBMITTED"

    validate_error(
        api.construction_completion(
            chain.loan_id,
            construction_completion_payload(
                final_inspection_passed=False,
                completion_note="Inspection not signed off",
            ),
            LOAN_SERVICER,
        ),
        ERR_INVALID_REQUEST,
        422,
    )

    validate_error(
        api.construction_completion(
            chain.loan_id,
            construction_completion_payload(completion_note="Attempt with an open draw"),
            LOAN_SERVICER,
        ),
        ERR_DRAW_INVALID_STATE,
        409,
    )

    rejected = get_success_data(
        api.reject_draw_request(
            draw["id"],
            draw_rejection_payload(inspector_note="Withdrawn by the borrower"),
            LOAN_SERVICER,
        )
    )
    assert rejected["status"] == "REJECTED"

    completed = get_success_data(
        api.construction_completion(
            chain.loan_id,
            construction_completion_payload(completion_note="Project closed out"),
            LOAN_SERVICER,
        )
    )
    assert_loan_ledger(
        completed,
        servicing_status="AMORTIZING",
        risk_posture="OPEN",
        principal_cents=225000000,
        disbursed_principal_cents=0,
        undrawn_commitment_cents=0,
        cancelled_commitment_cents=225000000,
        retainage_held_cents=0,
        retainage_released_cents=0,
    )
    assert_commitment_conservation(completed)

    validate_error(
        api.create_draw_request(
            draw_request_payload(
                chain.loan_id,
                project_phase="FINAL",
                requested_amount_cents=100000,
                percent_complete=1.0000,
            ),
            LOAN_SERVICER,
        ),
        ERR_LOAN_NOT_IN_DRAW_PHASE,
        409,
    )
