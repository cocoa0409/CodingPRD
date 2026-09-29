"""Every refusal wears the same envelope and its own status code, and every
refusal leaves the store exactly as it found it."""

import pytest
from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories, fixtures as fx
from test_helpers.api_client import api_client
from test_helpers.api_errors import ApiErrorId
from test_helpers.constants import UNRESOLVABLE_UUID
from test_helpers.test_users import (
    CLERK_HEADERS,
    IDDE_HEADERS,
    MANAGER_HEADERS,
    OPERATIONS_HEADERS,
    role_only_headers,
)
from test_helpers.types import UserRole

CLERK_WITHOUT_IDENTITY = role_only_headers(UserRole.UTILITY_BILLING_CLERK.value)


class TestEveryErrorFamilyAnswersInTheSameEnvelope:
    """Seven refusals covering 401, 403, 400, 404, 409, 412 and 409 again."""

    @pytest.fixture
    def remeasured_account(self, active_program):
        """A residential account remeasured once, so version 1 is superseded."""
        account = fx.create_account(
            active_program["term_id"],
            parcel_id="P-1000",
            parcel_class="RESIDENTIAL_SINGLE",
            impervious_area_sqft=3000.0,
            owner_name="Ada Owner",
        )
        updated = fx.remeasure_account(account["id"], 4500.0, account["version"])
        return {
            "term_id": active_program["term_id"],
            "account": account,
            "stale_version": account["version"],
            "current_version": updated["version"],
        }

    def test_01_an_omitted_identity_header_is_a_401(self, remeasured_account):
        """The role is authorised for the read and the identity is missing.

        PRD: "Every request — including the clock endpoint — must carry two headers.
        `X-User-ID` identifies the acting individual and `X-User-Role` declares the capacity
        in which they are acting. If `X-User-ID` is absent or does not name a known actor,
        the request is refused with `ERR_MISSING_USER_ID` (HTTP 401)."

        Design: Corner/errors/the_envelope_and_status_mapping_hold_across_every_error_family_including_a_missing_x_user_header
        """
        response = api_client.get_account(
            remeasured_account["account"]["id"], CLERK_WITHOUT_IDENTITY
        )

        validate_error(response, ApiErrorId.ERR_MISSING_USER_ID.value, 401)

    def test_02_a_role_outside_the_endpoint_is_a_403(self, remeasured_account):
        """A billing run belongs to the clerk, not to the investigator.

        PRD: "If the role in `X-User-Role` is not among those authorised for the endpoint,
        the request is refused with `ERR_UNAUTHORIZED` (HTTP 403)." And: "A role not listed
        for the endpoint yields `ERR_UNAUTHORIZED` (403). Because this precedes every
        existence and state check, an unauthorised caller can never learn whether a resource
        exists or what state it is in."

        Design: Corner/errors/the_envelope_and_status_mapping_hold_across_every_error_family_including_a_missing_x_user_header
        """
        response = api_client.create_billing_run(
            remeasured_account["term_id"],
            factories.billing_run_payload("FINAL", "2026-01-01", "2026-12-31"),
            IDDE_HEADERS,
        )

        validate_error(response, ApiErrorId.ERR_UNAUTHORIZED.value, 403)

    def test_03_an_unknown_enum_member_is_a_400(self, remeasured_account):
        """FARMLAND is not one of the four rate classes.

        PRD: "Missing required body fields, wrong types, unknown enum members,
        out-of-range numbers, malformed ISO 8601 values and out-of-range pagination all
        yield `ERR_VALIDATION` (400)." And: "the `parcel_class` rate class —
        `RESIDENTIAL_SINGLE`, `RESIDENTIAL_MULTI`, `COMMERCIAL` or `INSTITUTIONAL` — and the
        measured `impervious_area_sqft`, which may not be negative"

        Design: Corner/errors/the_envelope_and_status_mapping_hold_across_every_error_family_including_a_missing_x_user_header
        """
        response = api_client.create_account(
            factories.account_payload(
                remeasured_account["term_id"],
                parcel_id="P-2000",
                parcel_class="FARMLAND",
                impervious_area_sqft=100.0,
                owner_name="Ben Owner",
            ),
            CLERK_HEADERS,
        )

        validate_error(response, ApiErrorId.ERR_VALIDATION.value, 400)

    def test_04_an_unresolvable_path_identifier_is_a_404(self):
        """The identifier is well formed and names no stored account.

        PRD: "Every identifier in the path must resolve to a stored row, yielding the 404
        belonging to that entity kind." And: "An unknown account identifier is
        `ERR_ACCOUNT_NOT_FOUND`."

        Design: Corner/errors/the_envelope_and_status_mapping_hold_across_every_error_family_including_a_missing_x_user_header
        """
        response = api_client.get_account(UNRESOLVABLE_UUID, CLERK_HEADERS)

        validate_error(response, ApiErrorId.ERR_ACCOUNT_NOT_FOUND.value, 404)

    def test_05_a_parcel_billed_twice_in_one_term_is_a_409(self, remeasured_account):
        """The assessor's parcel identifier is claimed already.

        PRD: "`permit_number` is unique across all permit terms; `measure_code` is unique
        per term; `outfall_code` is unique per term; `parcel_id` is unique per term.
        Collisions yield `ERR_DUPLICATE_PERMIT_NUMBER`, `ERR_DUPLICATE_MEASURE_CODE`,
        `ERR_DUPLICATE_OUTFALL_CODE` and `ERR_DUPLICATE_PARCEL_ID` respectively, all HTTP
        409."

        Design: Corner/errors/the_envelope_and_status_mapping_hold_across_every_error_family_including_a_missing_x_user_header
        """
        response = api_client.create_account(
            factories.account_payload(
                remeasured_account["term_id"],
                parcel_id="P-1000",
                parcel_class="COMMERCIAL",
                impervious_area_sqft=100.0,
                owner_name="Ben Owner",
            ),
            CLERK_HEADERS,
        )

        validate_error(response, ApiErrorId.ERR_DUPLICATE_PARCEL_ID.value, 409)

    def test_06_a_superseded_account_version_is_a_412_and_changes_nothing(
        self, remeasured_account
    ):
        """The remeasurement already spent version 1, so version 1 is stale.

        PRD: "Recording a remeasured impervious area on a stormwater account requires
        `expected_stormwater_account_version` carrying the client's last observed `version`
        of that account. If the value does not equal the account's current `version`, the
        request is rejected with `ERR_ACCOUNT_VERSION_CONFLICT` (HTTP 412) and no field
        changes."

        Design: Corner/errors/the_envelope_and_status_mapping_hold_across_every_error_family_including_a_missing_x_user_header
        """
        account_id = remeasured_account["account"]["id"]

        response = api_client.create_impervious_update(
            account_id,
            factories.impervious_update_payload(
                6000.0, remeasured_account["stale_version"]
            ),
            CLERK_HEADERS,
        )

        validate_error(response, ApiErrorId.ERR_ACCOUNT_VERSION_CONFLICT.value, 412)

        account = fx.read_account(account_id)
        assert account["impervious_area_sqft"] == pytest.approx(4500.0, abs=0.01), (
            "the accepted remeasurement still stands, got "
            f"{account['impervious_area_sqft']}"
        )
        assert account["version"] == remeasured_account["current_version"], (
            "the refused write consumed no version, expected "
            f"{remeasured_account['current_version']}, got {account['version']}"
        )

    def test_07_the_same_status_can_carry_a_different_code(self, remeasured_account):
        """Activating an ACTIVE term is a 409, and not the duplicate one.

        PRD: "an attempt to activate a term that is not in `DRAFT` is
        `ERR_PERMIT_TERM_NOT_ACTIVE`." And: "The target row must be in a state from which
        the requested transition exists; otherwise the entity's state error is returned with
        HTTP 409"

        Design: Corner/errors/the_envelope_and_status_mapping_hold_across_every_error_family_including_a_missing_x_user_header
        """
        response = api_client.activate_permit_term(
            remeasured_account["term_id"], MANAGER_HEADERS
        )

        validate_error(response, ApiErrorId.ERR_PERMIT_TERM_NOT_ACTIVE.value, 409)

    def test_08_all_seven_refusals_wear_the_identical_envelope(
        self, remeasured_account
    ):
        """Seven codes, four statuses, one shape and never a resource payload.

        PRD: "The `meta` object for error responses contains only `api_request_id` and
        `api_request_timestamp`." And: "The `error_id` is a unique, machine-readable string
        that identifies the specific error." And: "The `message` provides a human-readable
        explanation of what went wrong."

        Design: Corner/errors/the_envelope_and_status_mapping_hold_across_every_error_family_including_a_missing_x_user_header
        """
        term_id = remeasured_account["term_id"]
        account_id = remeasured_account["account"]["id"]
        attempts = [
            (
                api_client.get_account(account_id, CLERK_WITHOUT_IDENTITY),
                ApiErrorId.ERR_MISSING_USER_ID.value,
                401,
            ),
            (
                api_client.create_billing_run(
                    term_id,
                    factories.billing_run_payload("FINAL", "2026-01-01", "2026-12-31"),
                    IDDE_HEADERS,
                ),
                ApiErrorId.ERR_UNAUTHORIZED.value,
                403,
            ),
            (
                api_client.create_account(
                    factories.account_payload(
                        term_id, parcel_id="P-2000", parcel_class="FARMLAND"
                    ),
                    CLERK_HEADERS,
                ),
                ApiErrorId.ERR_VALIDATION.value,
                400,
            ),
            (
                api_client.get_account(UNRESOLVABLE_UUID, CLERK_HEADERS),
                ApiErrorId.ERR_ACCOUNT_NOT_FOUND.value,
                404,
            ),
            (
                api_client.create_account(
                    factories.account_payload(
                        term_id, parcel_id="P-1000", parcel_class="COMMERCIAL"
                    ),
                    CLERK_HEADERS,
                ),
                ApiErrorId.ERR_DUPLICATE_PARCEL_ID.value,
                409,
            ),
            (
                api_client.create_impervious_update(
                    account_id,
                    factories.impervious_update_payload(
                        6000.0, remeasured_account["stale_version"]
                    ),
                    CLERK_HEADERS,
                ),
                ApiErrorId.ERR_ACCOUNT_VERSION_CONFLICT.value,
                412,
            ),
            (
                api_client.activate_permit_term(term_id, MANAGER_HEADERS),
                ApiErrorId.ERR_PERMIT_TERM_NOT_ACTIVE.value,
                409,
            ),
        ]

        for response, error_id, status in attempts:
            validate_error(response, error_id, status)
            body = response.json()
            assert set(body["meta"]) == {"api_request_id", "api_request_timestamp"}, (
                f"the error meta carries only the two request fields for {error_id}, "
                f"got {sorted(body['meta'])}"
            )
            assert set(body["data"]) == {"error_id", "message"}, (
                f"no resource payload rides along with {error_id}, "
                f"got {sorted(body['data'])}"
            )

        statuses = {status for _, _, status in attempts}
        assert statuses == {401, 403, 400, 404, 409, 412}, (
            f"six distinct statuses were exercised, got {sorted(statuses)}"
        )
        codes = {error_id for _, error_id, _ in attempts}
        assert len(codes) == 7, (
            f"seven distinct error codes were exercised, got {sorted(codes)}"
        )


class TestARejectedWriteLeavesNothingBehind:
    """Two refusals that would each have written several fields at once."""

    @pytest.fixture
    def loaded_program(self, active_program):
        """OF-01 full for August, and an account credited to its 0.5000 ceiling."""
        outfall = active_program["outfalls"]["OF-01"]
        fx.append_sweeping_run(outfall["id"], "2026-08-01", "2026-08-10", 40.00)
        account = fx.create_account(
            active_program["term_id"],
            parcel_id="P-1000",
            parcel_class="COMMERCIAL",
            impervious_area_sqft=9020.0,
            owner_name="Ada Owner",
        )
        fx.setup_approved_credit(account, requested_credit_pct=0.5000)
        credited = fx.read_account(account["id"])
        pending = fx.file_credit_application(credited, requested_credit_pct=0.0100)
        return {
            "outfall": fx.read_outfall(outfall["id"]),
            "measure_id": active_program["measures"]["MUNICIPAL_OPERATIONS"]["id"],
            "account_before": fx.read_account(account["id"]),
            "pending": pending,
        }

    def test_09_a_refused_sweeping_run_neither_logs_nor_counts(self, loaded_program):
        """August is full, and the refusal appends nothing to the log.

        PRD: "Separately, the lane miles attributed to any one calendar month — a run is
        attributed to the month of its `run_start_date` — may not exceed the outfall's
        `sweeping_capacity_lane_miles_per_month`; a run that would push the month's total
        past capacity is refused with `ERR_SWEEPING_CAPACITY_EXCEEDED`, even though the
        individual run looks perfectly plausible on its own." And: "Nothing is persisted
        when a request is rejected — no partial writes, no counter increments, no cascades."

        Design: Corner/errors/a_rejected_write_leaves_no_partial_state_or_version_bump
        """
        before = loaded_program["outfall"]

        response = api_client.create_sweeping_run(
            before["id"],
            factories.sweeping_run_payload("2026-08-20", "2026-08-25", 5.00),
            OPERATIONS_HEADERS,
        )

        validate_error(response, ApiErrorId.ERR_SWEEPING_CAPACITY_EXCEEDED.value, 422)

        after = fx.read_outfall(before["id"])
        assert len(after["sweeping_runs"]) == 1, (
            f"the log still holds only the accepted run, got {len(after['sweeping_runs'])}"
        )
        assert after["swept_lane_miles_ytd"] == pytest.approx(40.00, abs=0.01), (
            f"the total did not move, got {after['swept_lane_miles_ytd']}"
        )
        assert after["version"] == before["version"], (
            f"and no version was spent, expected {before['version']}, "
            f"got {after['version']}"
        )

    def test_10_the_refused_run_does_not_leak_into_the_measure_either(
        self, loaded_program
    ):
        """The mirrored lane-mile figure is a cascade, so it stays put too.

        PRD: "Each accepted run mirrors the term-wide lane-mile total into the
        `MUNICIPAL_OPERATIONS` control measure's `swept_lane_miles_ytd` — the sum of
        `lane_miles_swept` across the `sweeping_runs` of every `ACTIVE` outfall in the term
        — and copies that same figure into that measure's `measurable_goal_actual`, then
        recomputes its `attainment_pct` and `goal_status` and the term's posture." And:
        "Nothing is persisted when a request is rejected — no partial writes, no counter
        increments, no cascades."

        Design: Corner/errors/a_rejected_write_leaves_no_partial_state_or_version_bump
        """
        validate_error(
            api_client.create_sweeping_run(
                loaded_program["outfall"]["id"],
                factories.sweeping_run_payload("2026-08-20", "2026-08-25", 5.00),
                OPERATIONS_HEADERS,
            ),
            ApiErrorId.ERR_SWEEPING_CAPACITY_EXCEEDED.value,
            422,
        )

        measure = fx.read_measure(loaded_program["measure_id"])
        assert measure["swept_lane_miles_ytd"] == pytest.approx(40.00, abs=0.01), (
            "only the accepted 40.00 was ever mirrored, got "
            f"{measure['swept_lane_miles_ytd']}"
        )
        assert measure["measurable_goal_actual"] == pytest.approx(40.00, abs=0.01), (
            f"and the actual agrees with it, got {measure['measurable_goal_actual']}"
        )

    def test_11_a_refused_credit_review_moves_no_money_and_spends_no_version(
        self, loaded_program
    ):
        """The account is already at its ceiling and stays exactly there.

        PRD: "and that the account's existing approved credit total plus this
        `approved_credit_pct` does not exceed 0.5000, otherwise
        `ERR_CREDIT_CEILING_EXCEEDED`." And: "Nothing is persisted when a request is
        rejected — no partial writes, no counter increments, no cascades."

        Design: Corner/errors/a_rejected_write_leaves_no_partial_state_or_version_bump
        """
        before = loaded_program["account_before"]

        response = api_client.review_fee_credit_application(
            loaded_program["pending"]["id"],
            factories.credit_review_payload("APPROVE"),
            CLERK_HEADERS,
        )

        validate_error(response, ApiErrorId.ERR_CREDIT_CEILING_EXCEEDED.value, 422)

        after = fx.read_account(before["id"])
        assert after["total_credit_pct"] == pytest.approx(0.5000, abs=0.00005), (
            f"the credit pool is untouched, got {after['total_credit_pct']}"
        )
        assert after["current_net_fee_cents"] == 14632, (
            f"half of 29264 is still owed, got {after['current_net_fee_cents']}"
        )
        assert after["version"] == before["version"], (
            f"and no version was spent, expected {before['version']}, "
            f"got {after['version']}"
        )

    def test_12_the_refused_application_keeps_every_reviewer_field_null(
        self, loaded_program
    ):
        """A refused review leaves the row where the filing left it.

        PRD: "A new application has `status` `SUBMITTED`, `submitted_at` stamped from the
        logical clock, `applicant_user_id` set to the submitting actor,
        `approved_credit_pct`, `reviewed_by_user_id`, `approved_at`, `return_reason`,
        `revoked_reason` and `revoked_at` null, and `resubmission_count` at 0." And:
        "Nothing is persisted when a request is rejected — no partial writes, no counter
        increments, no cascades."

        Design: Corner/errors/a_rejected_write_leaves_no_partial_state_or_version_bump
        """
        application_id = loaded_program["pending"]["id"]
        validate_error(
            api_client.review_fee_credit_application(
                application_id,
                factories.credit_review_payload("APPROVE"),
                CLERK_HEADERS,
            ),
            ApiErrorId.ERR_CREDIT_CEILING_EXCEEDED.value,
            422,
        )

        application = fx.read_application(application_id)
        assert application["status"] == "SUBMITTED", (
            f"the application still awaits a decision, got {application['status']}"
        )
        assert application["approved_credit_pct"] is None, "nothing was granted"
        assert application["reviewed_by_user_id"] is None, "no reviewer was recorded"
        assert application["approved_at"] is None, "and no approval was stamped"
        assert application["version"] == loaded_program["pending"]["version"], (
            "the row's own version is unchanged, expected "
            f"{loaded_program['pending']['version']}, got {application['version']}"
        )

    def test_13_the_same_writes_succeed_once_the_aggregate_leaves_room(
        self, loaded_program
    ):
        """September has capacity and a revoked grant frees the ceiling.

        PRD: "Each accepted run is appended to the outfall's append-only `sweeping_runs`
        list as an entry holding `run_start_date`, `run_end_date` and `lane_miles_swept`,
        and raises the outfall's `swept_lane_miles_ytd`, which is the sum of
        `lane_miles_swept` over the whole list to 2 decimal places." And:
        "`gross_billable_cents` is `gross_fee_cents` plus `class_surcharge_cents`."

        Design: Corner/errors/a_rejected_write_leaves_no_partial_state_or_version_bump
        """
        outfall_id = loaded_program["outfall"]["id"]
        validate_success(
            api_client.create_sweeping_run(
                outfall_id,
                factories.sweeping_run_payload("2026-09-01", "2026-09-05", 5.00),
                OPERATIONS_HEADERS,
            ),
            200,
        )

        outfall = fx.read_outfall(outfall_id)
        assert len(outfall["sweeping_runs"]) == 2, (
            f"the second run was logged, got {len(outfall['sweeping_runs'])}"
        )
        assert outfall["swept_lane_miles_ytd"] == pytest.approx(45.00, abs=0.01), (
            f"40.00 and 5.00 sum to 45.00, got {outfall['swept_lane_miles_ytd']}"
        )

        account = fx.read_account(loaded_program["account_before"]["id"])
        assert account["gross_billable_cents"] == 29264, (
            "the fee chain was never disturbed by the refusals, got "
            f"{account['gross_billable_cents']}"
        )
