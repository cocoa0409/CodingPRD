"""Two independent physician dimensions, and the claim appeal cycle."""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import (
    CLAIMS_EXAMINER_HEADERS,
    ERR_INVALID_STATE_TRANSITION,
    NETWORK_MANAGER_HEADERS,
    approve_claim,
    assert_fields,
    assign_enrollee,
    create_active_agreement,
    create_active_physician,
    create_claim,
    create_enrollee,
    create_pool,
    deny_claim,
    give_exit_notice,
    pay_claim_state,
    read_claim,
    read_enrollee,
    read_physician,
    read_pool,
    set_clock,
    state_payload,
)


def _set_panel_status(api, physician_id, panel_status):
    response = api.set_panel_status(
        physician_id, {"panel_status": panel_status}, NETWORK_MANAGER_HEADERS
    )
    return validate_success(response, 200)


def _rescind_notice(api, physician_id):
    response = api.set_physician_state(
        physician_id, state_payload("ACTIVE"), NETWORK_MANAGER_HEADERS
    )
    return validate_success(response, 200)


def _appeal_claim(api, claim_id):
    response = api.set_claim_state(
        claim_id, state_payload("RECEIVED"), NETWORK_MANAGER_HEADERS
    )
    return response


def _void_claim(api, claim_id):
    response = api.set_claim_state(
        claim_id, state_payload("VOIDED"), CLAIMS_EXAMINER_HEADERS
    )
    return validate_success(response, 200)


def _physician_on_the_first_of_march(api):
    agreement = create_active_agreement(api, max_panel_size=5)
    physician = create_active_physician(api, agreement["id"])
    set_clock(api, "2026-03-01T00:00:00Z")
    return agreement, physician


class TestPhysicianParallelDimensions:
    def test_exit_notice_stamps_the_clock_and_derives_the_continuity_window(self, api):
        """PRD §3.2: "`continuity_of_care_until` is derived as `exit_notice_at`
        advanced by the agreement's `continuity_of_care_days` — ninety days by
        default, so a notice given on the first of March protects that panel
        until the twenty-ninth of May"

        Design: Difficulty/non_linear_state_machine/physician_parallel_credential_and_panel_dimensions
        """
        _agreement, physician = _physician_on_the_first_of_march(api)
        noticed = give_exit_notice(api, physician["id"])

        assert_fields(
            noticed,
            {
                "credential_status": "NOTICE_GIVEN",
                "exit_notice_at": "2026-03-01T00:00:00Z",
                "continuity_of_care_until": "2026-05-30T00:00:00Z",
            },
        )

    def test_closing_the_panel_leaves_the_credential_dimension_untouched(self, api):
        """PRD §3.2: "Neither dimension constrains the other's legal moves except
        where a precondition below says so explicitly."

        Design: Difficulty/non_linear_state_machine/physician_parallel_credential_and_panel_dimensions
        """
        _agreement, physician = _physician_on_the_first_of_march(api)
        closed = _set_panel_status(api, physician["id"], "CLOSED_TO_NEW")

        assert_fields(
            closed, {"panel_status": "CLOSED_TO_NEW", "credential_status": "ACTIVE"}
        )

    def test_notice_over_an_already_closed_panel_does_not_disturb_the_panel(self, api):
        """PRD §3.2: "and `panel_status` is set to `CLOSED_TO_NEW` if and only if
        it was `OPEN`, leaving `TRANSFER_PENDING` and `TRANSFERRED` untouched"

        Design: Difficulty/non_linear_state_machine/physician_parallel_credential_and_panel_dimensions
        """
        _agreement, physician = _physician_on_the_first_of_march(api)
        _set_panel_status(api, physician["id"], "CLOSED_TO_NEW")
        noticed = give_exit_notice(api, physician["id"])

        assert noticed["panel_status"] == "CLOSED_TO_NEW"
        assert noticed["credential_status"] == "NOTICE_GIVEN"

    def test_rescinding_notice_clears_the_window_but_does_not_reopen_the_panel(
        self, api
    ):
        """PRD §3.2: "The move is reversible: a `NetworkManager` may take
        `NOTICE_GIVEN → ACTIVE`, which restores `credential_status` to `ACTIVE`,
        clears `exit_notice_at` back to null, clears `continuity_of_care_until`
        back to null, and leaves `panel_status` exactly as it stood — the panel
        is not reopened by rescinding the notice."

        Design: Difficulty/non_linear_state_machine/physician_parallel_credential_and_panel_dimensions
        """
        _agreement, physician = _physician_on_the_first_of_march(api)
        _set_panel_status(api, physician["id"], "CLOSED_TO_NEW")
        give_exit_notice(api, physician["id"])
        rescinded = _rescind_notice(api, physician["id"])

        assert_fields(
            rescinded,
            {
                "credential_status": "ACTIVE",
                "exit_notice_at": None,
                "continuity_of_care_until": None,
                "panel_status": "CLOSED_TO_NEW",
            },
        )

    def test_the_panel_reopens_only_as_a_separate_explicit_act(self, api):
        """PRD §3.2: "Reopening — `CLOSED_TO_NEW → OPEN` — is reserved to a
        `NetworkManager` and carries three preconditions: `panel_status` must be
        `CLOSED_TO_NEW`, `credential_status` must be `ACTIVE`, and the
        agreement's `capitation_posture` must read `CURRENT`."

        Design: Difficulty/non_linear_state_machine/physician_parallel_credential_and_panel_dimensions
        """
        _agreement, physician = _physician_on_the_first_of_march(api)
        _set_panel_status(api, physician["id"], "CLOSED_TO_NEW")
        give_exit_notice(api, physician["id"])
        _rescind_notice(api, physician["id"])
        reopened = _set_panel_status(api, physician["id"], "OPEN")

        assert reopened["panel_status"] == "OPEN"
        assert reopened["credential_status"] == "ACTIVE"
        assert read_physician(api, physician["id"])["panel_status"] == "OPEN"


def _two_claims_under_one_pool(api):
    set_clock(api, "2026-01-01T00:00:00Z")
    agreement = create_active_agreement(api, max_panel_size=5)
    physician = create_active_physician(api, agreement["id"])
    pool = create_pool(api, agreement["id"], pool_type="PROFESSIONAL")
    enrollee = create_enrollee(api, agreement["id"], risk_score_bps=10000)
    assign_enrollee(api, enrollee["id"], physician["id"])

    set_clock(api, "2026-07-01T00:00:00Z")
    first = create_claim(
        api,
        agreement["id"],
        enrollee["id"],
        physician["id"],
        billed_cents=20000,
        service_date="2026-06-15T00:00:00Z",
    )
    second = create_claim(
        api,
        agreement["id"],
        enrollee["id"],
        physician["id"],
        billed_cents=15000,
        service_date="2026-06-15T00:00:00Z",
    )
    return {
        "agreement": agreement,
        "physician": physician,
        "pool": pool,
        "enrollee": enrollee,
        "first": first,
        "second": second,
    }


class TestClaimDenialAppealCycle:
    def test_denial_records_zero_allowed_rather_than_null(self, api):
        """PRD §3.6: "Denial records the `denial_reason`, sets `allowed_cents` to
        0 — note that this is zero, not null, which is what distinguishes a
        denied claim from a never-adjudicated one — and advances the `version` by
        1."

        Design: Difficulty/non_linear_state_machine/downstream_claim_denial_appeal_cycle_and_branch
        """
        built = _two_claims_under_one_pool(api)
        assert built["first"]["allowed_cents"] is None

        denied = deny_claim(api, built["first"]["id"], "NO_AUTHORIZATION")
        assert_fields(
            denied,
            {
                "status": "ADJUDICATED_DENIED",
                "allowed_cents": 0,
                "denial_reason": "NO_AUTHORIZATION",
                "appeal_count": 0,
            },
        )

    def test_appeal_returns_the_claim_to_received_and_clears_the_adjudication(
        self, api
    ):
        """PRD §3.6: "The appeal sets `status` back to `RECEIVED`, increases
        `appeal_count` by 1, clears `denial_reason` to null, and clears
        `allowed_cents` back to null so the re-adjudication starts clean."

        Design: Difficulty/non_linear_state_machine/downstream_claim_denial_appeal_cycle_and_branch
        """
        built = _two_claims_under_one_pool(api)
        deny_claim(api, built["first"]["id"], "NO_AUTHORIZATION")
        appealed = validate_success(_appeal_claim(api, built["first"]["id"]), 200)

        assert_fields(
            appealed,
            {
                "status": "RECEIVED",
                "appeal_count": 1,
                "denial_reason": None,
                "allowed_cents": None,
            },
        )

    def test_third_appeal_is_refused_and_leaves_the_count_at_two(self, api):
        """PRD §3.6: "A third appeal — one attempted while `appeal_count` already
        reads 2 — is refused with `ERR_INVALID_STATE_TRANSITION`."

        Design: Difficulty/non_linear_state_machine/downstream_claim_denial_appeal_cycle_and_branch
        """
        built = _two_claims_under_one_pool(api)
        claim_id = built["first"]["id"]

        deny_claim(api, claim_id, "NO_AUTHORIZATION")
        validate_success(_appeal_claim(api, claim_id), 200)
        deny_claim(api, claim_id, "NOT_COVERED")
        second_appeal = validate_success(_appeal_claim(api, claim_id), 200)
        assert second_appeal["appeal_count"] == 2

        exhausted = deny_claim(api, claim_id, "DUPLICATE")
        assert_fields(
            exhausted,
            {
                "status": "ADJUDICATED_DENIED",
                "denial_reason": "DUPLICATE",
                "allowed_cents": 0,
            },
        )

        refused = _appeal_claim(api, claim_id)
        validate_error(refused, ERR_INVALID_STATE_TRANSITION, 409)

        unchanged = read_claim(api, claim_id)
        assert unchanged["appeal_count"] == 2
        assert unchanged["status"] == "ADJUDICATED_DENIED"

    def test_exhausted_denial_may_be_voided_with_no_ledger_movement(self, api):
        """PRD §3.6: "A claim exhausted in this way may be closed out: a
        `ClaimsExaminer` takes `ADJUDICATED_DENIED → VOIDED`, permitted when
        `status` is `ADJUDICATED_DENIED` and `appeal_count` is exactly 2, which
        sets `status` to `VOIDED` with no ledger movement whatsoever because the
        claim never paid."

        Design: Difficulty/non_linear_state_machine/downstream_claim_denial_appeal_cycle_and_branch
        """
        built = _two_claims_under_one_pool(api)
        claim_id = built["first"]["id"]

        deny_claim(api, claim_id, "NO_AUTHORIZATION")
        validate_success(_appeal_claim(api, claim_id), 200)
        deny_claim(api, claim_id, "NOT_COVERED")
        validate_success(_appeal_claim(api, claim_id), 200)
        deny_claim(api, claim_id, "DUPLICATE")

        voided = _void_claim(api, claim_id)
        assert voided["status"] == "VOIDED"
        assert voided["paid_cents"] is None
        assert read_pool(api, built["pool"]["id"])["paid_claims_cents"] == 0

    def test_the_approved_sibling_claim_still_pays_into_the_pool(self, api):
        """PRD §3.6: "First, `status` becomes `PAID` and `paid_cents` is set
        equal to `allowed_cents`."

        Design: Difficulty/non_linear_state_machine/downstream_claim_denial_appeal_cycle_and_branch
        """
        built = _two_claims_under_one_pool(api)
        approve_claim(api, built["second"]["id"], 15000)
        paid = pay_claim_state(api, built["second"]["id"])

        assert_fields(paid, {"status": "PAID", "paid_cents": 15000})
        assert read_pool(api, built["pool"]["id"])["paid_claims_cents"] == 15000
        assert (
            read_enrollee(api, built["enrollee"]["id"])["cumulative_paid_claims_cents"]
            == 15000
        )
