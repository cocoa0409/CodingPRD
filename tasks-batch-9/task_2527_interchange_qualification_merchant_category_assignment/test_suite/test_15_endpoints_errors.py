"""Endpoint shapes — create/read/list round trips, action endpoints, computed
reads and cross-reference resolution — plus the not-found half of the error
catalogue.
"""
from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers.api_client import api_client
from test_helpers.factories import (
    make_implementation_window_payload,
    make_rate_program_payload,
)
from test_helpers.fixtures import (
    board_merchant,
    canonical_environment,
    create_incentive_program,
    define_mccs,
    draft_rate_version,
    complete_window,
    enrol_merchant,
    publish_rate_version,
    read_enrollment,
    read_incentive_program,
    schedule_window,
    set_clock,
    start_window,
)
from test_helpers.test_users import TEST_USERS

NETWORK_ADMIN = TEST_USERS["network_admin_headers"]
ANY_ACQUIRER_OPS = TEST_USERS["acquirer_ops_headers"]
COMPLIANCE_AUDITOR = TEST_USERS["compliance_auditor_headers"]
CLOCK = "2026-09-03T00:00:00Z"
PUBLICATION_CLOCK = "2026-09-01T12:00:00Z"
PUBLICATION_STAMP = "2026-09-01T12:00:00.000Z"
TWO_ELEMENTS = ["AUTH_CODE", "TERMINAL_ID"]


def _expect_not_found(response, expected_error_id):
    assert response.status_code == 404
    error = validate_error(response, expected_error_id, 404)
    assert isinstance(error["message"], str)
    assert error["message"] != ""
    assert response.json()["response_type"] == "error"
    return error


class TestCreateReadListRoundTrip:
    def test_a_rate_program_reads_back_unchanged_and_lists_once(self):
        """The catalogue is create-read-list only, so the stored tier must come back
        exactly as declared, sit at its opening version, and appear once under a
        category filter.

        PRD 2.4: "`version` is an integer that starts at 1 when the row is created and
        increments by exactly 1 on every mutation of that row."

        PRD 3.2: "Its price has two components: `base_rate_bps`, an ad-valorem rate
        from 0 through 1000 basis points, and `per_item_fee_cents`, a flat
        per-transaction fee from 0 through 500 cents added after the ad-valorem
        component."

        PRD 3.2: "Finally `max_clearing_delay_hours`, from 0 through 8760, is the
        largest clearing delay the program tolerates — a constraint that, importantly,
        is only enforced at finalization and not at record intake."

        Design: Corner/endpoints/endpoint_standard_crud_rate_program_create_read_and_list_round_trip
        """
        set_clock(CLOCK)
        define_mccs(["5411"])

        created = api_client.create_rate_program(
            make_rate_program_payload(
                "SMALL_TICKET_STD",
                "SMALL_TICKET",
                ["5411"],
                name="Small Ticket",
                base_rate_bps=165,
                per_item_fee_cents=4,
                requires_data_elements=TWO_ELEMENTS,
                max_clearing_delay_hours=48,
            ),
            NETWORK_ADMIN,
        )
        assert created.status_code == 201
        program = validate_success(created, 201)
        assert program["version"] == 1

        read_back = validate_success(
            api_client.get_rate_program(program["id"], ANY_ACQUIRER_OPS)
        )
        assert read_back["program_code"] == "SMALL_TICKET_STD"
        assert read_back["base_rate_bps"] == 165
        assert read_back["per_item_fee_cents"] == 4
        assert read_back["max_clearing_delay_hours"] == 48

        rows, meta = validate_paginated(
            api_client.list_rate_programs(
                NETWORK_ADMIN,
                params={"category": "SMALL_TICKET", "limit": 10, "offset": 0},
            )
        )
        assert meta["total_count"] == 1
        assert meta["has_more"] is False
        assert rows[0]["id"] == program["id"]


class TestActionEndpoints:
    def test_starting_then_completing_a_window_reaches_the_terminal_completed(self):
        """The two action endpoints walk the window from scheduled to in progress to
        completed, stamping the start from the logical clock and leaving the acquirer
        compliant with nothing missed.

        PRD 3.2: "Starting a window advances it `SCHEDULED → IN_PROGRESS` and stamps
        `started_at` with the current logical-clock instant; it requires the referenced
        rate version still to be `PUBLISHED`."

        PRD 3.2: "Reporting completion from `IN_PROGRESS` advances the window to
        `COMPLETED`, stores the supplied `completion_note`, and recomputes the
        acquirer's `missed_window_count`."

        PRD 3.2: "`missed_window_count` is the number of implementation windows
        belonging to the acquirer that currently sit in `MISSED`, and it is recomputed
        on every window status change."

        Design: Corner/endpoints/endpoint_action_implementation_window_start_then_complete_reaches_completed
        """
        env = canonical_environment(PUBLICATION_CLOCK, program_keys=("STANDARD",))
        acquirer_id = env["acquirer"]["id"]
        acquirer_headers = env["acquirer_headers"]
        version = draft_rate_version(
            env["programs"]["STANDARD"]["id"],
            "2026Q4",
            "2026-10-01T00:00:00Z",
            "2027-01-01T00:00:00Z",
            "2026-09-30T00:00:00Z",
        )
        published = publish_rate_version(version["id"])
        assert published["status"] == "PUBLISHED"

        window = schedule_window(
            acquirer_id,
            version["id"],
            env["platform"]["id"],
            "2026-09-05T00:00:00Z",
            "2026-09-10T00:00:00Z",
            headers=acquirer_headers,
        )
        assert window["status"] == "SCHEDULED"

        started = start_window(window["id"], headers=acquirer_headers)
        assert started["status"] == "IN_PROGRESS"
        assert started["started_at"] == PUBLICATION_STAMP

        done = complete_window(
            window["id"],
            headers=acquirer_headers,
            completion_note="Rates deployed to all endpoints.",
        )
        assert done["status"] == "COMPLETED"
        assert done["completion_note"] == "Rates deployed to all endpoints."

        acquirer = validate_success(api_client.get_acquirer(acquirer_id, NETWORK_ADMIN))
        assert acquirer["missed_window_count"] == 0
        assert acquirer["compliance_status"] == "COMPLIANT"


class TestComputedReads:
    def test_the_pool_read_reflects_both_debits_and_closes_the_programme(self):
        """Two admissions against a twenty-million-cent pool leave five million free,
        which is below the minimum commitment, so the read shows both the debited
        remainder and the closed enrollment state.

        PRD 3.8: "It resolves to `ENROLLED` when the program's `enrollment_state` is
        `OPEN` and the requested `committed_volume_cents` is at most the program's
        `uncommitted_capacity_cents`; `enrolled_at` is then stamped with the current
        logical-clock instant, `uncommitted_capacity_cents` is debited by the committed
        volume, `enrolled_count` rises by 1, and `IncentiveProgram.version` advances by
        1."

        PRD 3.8: "After any capacity debit — a fresh enrollment or a waitlist promotion
        — the program moves `OPEN → CLOSED_FULL` if the remaining
        `uncommitted_capacity_cents` has fallen strictly below `min_commitment_cents`,
        on the reasoning that a pool too small to admit even a minimum commitment is
        functionally full."

        Design: Corner/endpoints/endpoint_computed_read_incentive_program_capacity_reflects_the_enrollment_debit
        """
        env = canonical_environment(CLOCK, program_keys=("STANDARD",))
        acquirer_id = env["acquirer"]["id"]
        merchant_a = board_merchant(acquirer_id, "GROCERY", legal_name="Grocer A")
        merchant_b = board_merchant(acquirer_id, "GROCERY", legal_name="Grocer B")
        assert merchant_a["mcc_status"] == "VERIFIED"
        assert merchant_b["mcc_status"] == "VERIFIED"

        program = create_incentive_program(
            eligible_mcc_codes=["5411"],
            total_capacity_cents=20000000,
            min_commitment_cents=6000000,
            reopen_threshold_cents=6000000,
            performance_threshold_pct=80.00,
        )
        enrollment_a = enrol_merchant(
            program["id"],
            merchant_a["id"],
            6000000,
            acquirer_id,
            expected_incentive_program_version=program["version"],
        )
        midpoint = read_incentive_program(program["id"])
        assert midpoint["uncommitted_capacity_cents"] == 14000000
        assert midpoint["enrollment_state"] == "OPEN"

        enrollment_b = enrol_merchant(
            program["id"],
            merchant_b["id"],
            9000000,
            acquirer_id,
            expected_incentive_program_version=midpoint["version"],
        )

        final = validate_success(
            api_client.get_incentive_program(program["id"], COMPLIANCE_AUDITOR)
        )
        assert final["total_capacity_cents"] == 20000000
        assert final["uncommitted_capacity_cents"] == 5000000
        assert final["enrolled_count"] == 2
        assert final["enrollment_state"] == "CLOSED_FULL"
        assert read_enrollment(enrollment_a["id"])["status"] == "ENROLLED"
        assert read_enrollment(enrollment_b["id"])["status"] == "ENROLLED"


class TestCrossReferenceResolution:
    def test_one_unresolvable_link_target_prevents_the_whole_window(self):
        """The window links three parents at once; only the rate version fails to
        resolve, and the response names that entity while no partial window is
        persisted.

        PRD 2.5: "Identifiers supplied in a request body are resolved after the path
        and after the request-shape check, in the order the endpoint declares its input
        fields; again the first unresolvable reference wins."

        PRD 2.5: "Body-reference resolution applies to acquirer creation (its platform
        reference), implementation window creation (its acquirer, rate program version
        and platform references), merchant boarding (its acquirer reference),
        reclassification request creation (its merchant reference), batch opening (its
        acquirer reference), clearing record addition (its merchant reference),
        enrollment creation (its program and merchant references) and audit creation
        (its merchant reference)."

        Design: Corner/endpoints/endpoint_cross_reference_link_window_with_an_unknown_rate_version_returns_404
        """
        env = canonical_environment(PUBLICATION_CLOCK, program_keys=())
        acquirer_id = env["acquirer"]["id"]

        response = api_client.create_implementation_window(
            make_implementation_window_payload(
                acquirer_id,
                NON_EXISTENT_UUID,
                env["platform"]["id"],
                "2026-09-05T00:00:00Z",
                "2026-09-10T00:00:00Z",
            ),
            env["acquirer_headers"],
        )
        _expect_not_found(response, "ERR_RATE_VERSION_NOT_FOUND")

        _rows, meta = validate_paginated(
            api_client.list_implementation_windows(NETWORK_ADMIN)
        )
        assert meta["total_count"] == 0


class TestNotFoundCodesAreEntitySpecific:
    def test_the_reference_data_paths_each_name_their_own_entity(self):
        """Six reference-data reads against the same unknown identifier return six
        different codes rather than one shared generic 404.

        PRD 2.5: "Identifiers embedded in a request URL are resolved strictly left to
        right, in the order they appear in the path."

        PRD 2.5: "The fourteen not-found codes are `ERR_PLATFORM_NOT_FOUND`,
        `ERR_ACQUIRER_NOT_FOUND`, `ERR_MCC_DEFINITION_NOT_FOUND`,
        `ERR_MERCHANT_NOT_FOUND`, `ERR_RATE_PROGRAM_NOT_FOUND`,
        `ERR_RATE_VERSION_NOT_FOUND`, `ERR_WINDOW_NOT_FOUND`, `ERR_BATCH_NOT_FOUND`,
        `ERR_RECORD_NOT_FOUND`, `ERR_RECLASS_REQUEST_NOT_FOUND`,
        `ERR_INCENTIVE_PROGRAM_NOT_FOUND`, `ERR_ENROLLMENT_NOT_FOUND`,
        `ERR_AUDIT_NOT_FOUND` and `ERR_FX_RATE_NOT_FOUND`, each with HTTP 404 and each
        naming the entity type whose identifier failed to resolve."

        PRD 2.2: "The `error_id` is a unique, machine-readable string that identifies the
        specific error."

        Design: Corner/errors/errors_not_found_sweep_over_the_reference_data_paths_returns_404
        """
        set_clock(CLOCK)

        codes = [
            _expect_not_found(
                api_client.get_acquirer(NON_EXISTENT_UUID, NETWORK_ADMIN),
                "ERR_ACQUIRER_NOT_FOUND",
            )["error_id"],
            _expect_not_found(
                api_client.get_mcc_definition(NON_EXISTENT_UUID, NETWORK_ADMIN),
                "ERR_MCC_DEFINITION_NOT_FOUND",
            )["error_id"],
            _expect_not_found(
                api_client.get_rate_program(NON_EXISTENT_UUID, NETWORK_ADMIN),
                "ERR_RATE_PROGRAM_NOT_FOUND",
            )["error_id"],
            _expect_not_found(
                api_client.get_rate_program_version(NON_EXISTENT_UUID, NETWORK_ADMIN),
                "ERR_RATE_VERSION_NOT_FOUND",
            )["error_id"],
            _expect_not_found(
                api_client.get_implementation_window(NON_EXISTENT_UUID, NETWORK_ADMIN),
                "ERR_WINDOW_NOT_FOUND",
            )["error_id"],
            _expect_not_found(
                api_client.get_fx_rate(NON_EXISTENT_UUID, NETWORK_ADMIN),
                "ERR_FX_RATE_NOT_FOUND",
            )["error_id"],
        ]
        assert len(set(codes)) == 6

    def test_the_clearing_and_programme_paths_each_name_their_own_entity(self):
        """The clearing, reclassification, incentive and audit aggregates complete the
        catalogue, again with one distinct code per aggregate.

        PRD 2.5: "The first identifier that does not resolve to a stored row terminates
        the request with HTTP 404 and the not-found code belonging to that identifier's
        entity type, so a request against a record inside a batch that does not exist
        reports the missing batch rather than the missing record."

        PRD 5: "Every error response carries the identifier below in `data.error_id`
        together with the HTTP status shown."

        Design: Corner/errors/errors_not_found_sweep_over_the_clearing_and_program_paths_returns_404
        """
        set_clock(CLOCK)

        codes = [
            _expect_not_found(
                api_client.get_settlement_batch(NON_EXISTENT_UUID, NETWORK_ADMIN),
                "ERR_BATCH_NOT_FOUND",
            )["error_id"],
            _expect_not_found(
                api_client.get_transaction_record(NON_EXISTENT_UUID, NETWORK_ADMIN),
                "ERR_RECORD_NOT_FOUND",
            )["error_id"],
            _expect_not_found(
                api_client.get_reclassification_request(
                    NON_EXISTENT_UUID, NETWORK_ADMIN
                ),
                "ERR_RECLASS_REQUEST_NOT_FOUND",
            )["error_id"],
            _expect_not_found(
                api_client.get_incentive_program(NON_EXISTENT_UUID, NETWORK_ADMIN),
                "ERR_INCENTIVE_PROGRAM_NOT_FOUND",
            )["error_id"],
            _expect_not_found(
                api_client.get_incentive_enrollment(NON_EXISTENT_UUID, NETWORK_ADMIN),
                "ERR_ENROLLMENT_NOT_FOUND",
            )["error_id"],
            _expect_not_found(
                api_client.get_merchant_category_audit(
                    NON_EXISTENT_UUID, NETWORK_ADMIN
                ),
                "ERR_AUDIT_NOT_FOUND",
            )["error_id"],
        ]
        assert len(set(codes)) == 6
