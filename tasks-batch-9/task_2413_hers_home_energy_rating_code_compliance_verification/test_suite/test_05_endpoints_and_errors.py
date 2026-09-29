"""Endpoint behaviour and the §5 error catalogue's not-found resolution."""

from datetime import datetime

import pytest
from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories
from test_helpers.api_errors import (
    ERR_BUILDER_NOT_FOUND,
    ERR_CORRECTIVE_ACTION_NOT_FOUND,
    ERR_DOCUMENT_PACKAGE_NOT_FOUND,
    ERR_HOME_NOT_FOUND,
    ERR_INSPECTION_NOT_FOUND,
    ERR_PLAN_MODEL_NOT_FOUND,
    ERR_QA_REVIEW_NOT_FOUND,
    ERR_RATER_NOT_FOUND,
    ERR_SAMPLE_SET_NOT_FOUND,
    ERR_SUBDIVISION_NOT_FOUND,
)
from test_helpers.assertions import (
    assert_builder_ledger,
    assert_coverage_ledger,
    assert_count,
    assert_index,
    assert_package_state,
    assert_rater_standing,
)
from test_helpers.fixtures import (
    build_confirmed_world,
    build_rating_world,
    build_registered_world,
    create_builder,
    create_home,
    create_plan_model,
    create_rater,
    create_subdivision,
    draft_package,
    get_builder,
    get_inspection,
    get_rater,
    get_rating,
    get_subdivision,
    issue_package,
    list_packages,
    record_test,
    schedule_inspection,
    set_clock,
)
from test_helpers.test_users import (
    ADMIN_HEADERS,
    make_builder_rep_headers,
    make_certified_rater_headers,
)

CLOCK_START = "2026-08-01T00:00:00Z"
CLOCK_OVERRIDE = "2026-08-25T14:30:00Z"


def instant(timestamp):
    """Parse an ISO 8601 UTC timestamp into a comparable instant."""
    return datetime.fromisoformat(timestamp.replace("Z", "+00:00"))


class TestLogicalClock:
    def test_diagnostic_tests_are_stamped_from_the_logical_clock(self, api):
        """§2.5: "The server does not read wall-clock time."

        §2.5: "It maintains a single **logical clock** which, before any client sets it, reads exactly `2026-08-01T00:00:00Z`, and it never falls back to real time."

        §2.5: "Everything time-derived in this system reads that clock: a rater's effective certification status, a diagnostic test's `performed_at_utc`, a rating's `confirmed_at`, and a documentation package's `issued_at`."

        §2.5: "A `RatingProviderAdmin` may move the clock by supplying `to_iso8601`; the response reports the new `current_utc`."

        Design: Corner/endpoints/logical_clock_default_and_override_stamp_diagnostic_tests
        """
        world = build_rating_world(api, lot_number="L-7001", permit_date="2026-08-05")
        inspection = schedule_inspection(
            api,
            world.rating_id,
            world.inspector_id,
            checkpoint="FINAL",
            scheduled_start_utc="2026-08-20T09:00:00Z",
            scheduled_end_utc="2026-08-20T11:00:00Z",
            air_handler_installed=True,
        )

        before = record_test(
            api, inspection["id"], world.inspector_id, "BLOWER_DOOR", 1080
        )
        clock = set_clock(api, CLOCK_OVERRIDE)
        after = record_test(
            api, inspection["id"], world.inspector_id, "DUCT_LEAKAGE_TOTAL", 96
        )

        assert instant(before["performed_at_utc"]) == instant(CLOCK_START), before
        assert instant(clock["current_utc"]) == instant(CLOCK_OVERRIDE), clock
        assert instant(after["performed_at_utc"]) == instant(CLOCK_OVERRIDE), after
        assert_rater_standing(
            get_rater(api, world.rater_id), effective_certification_status="ACTIVE"
        )
        assert get_inspection(api, inspection["id"])["status"] == "SCHEDULED"


class TestDocumentationPackageEndpoints:
    def test_redrafting_the_same_package_type_supersedes_the_earlier_draft(self, api):
        """§3.9: "A draft is created with `status` of `DRAFT`, a null `certified_amount_cents`, a null `revocation_reason` and a null `issued_at`; any earlier package of the *same* `package_type` on the *same* rating that is still at `DRAFT` becomes `SUPERSEDED`, and the drafting itself raises the rating's `version` by one."

        §2.9: "A successful draft itself increases the rating's `version` by 1, which means a client wishing to draft twice in a row must re-read the rating in between."

        §3.9: "An index of 45 or lower earns 250,000 cents — two thousand five hundred dollars."

        Design: Corner/endpoints/redrafting_a_package_supersedes_the_previous_draft
        """
        world = build_confirmed_world(
            api, lot_number="L-7101", permit_date="2026-08-05"
        )
        version_at_confirmation = world.rating["version"]

        first = validate_success(
            api.create_document_package(
                factories.document_package_payload(
                    world.rating_id,
                    version_at_confirmation,
                    package_type="TAX_CREDIT_45L",
                ),
                world.rep_headers,
            ),
            201,
        )
        refreshed = get_rating(api, world.rating_id)
        assert refreshed["version"] == version_at_confirmation + 1, refreshed

        second = validate_success(
            api.create_document_package(
                factories.document_package_payload(
                    world.rating_id, refreshed["version"], package_type="TAX_CREDIT_45L"
                ),
                world.rep_headers,
            ),
            201,
        )

        packages = {item["id"]: item for item in list_packages(api, world.rating_id)}
        assert_count(list(packages), 2)
        assert_package_state(packages[first["id"]], status="SUPERSEDED")
        assert_package_state(
            packages[second["id"]],
            status="DRAFT",
            provisional_amount_cents=250000,
            certified_amount_cents=None,
        )
        assert get_rating(api, world.rating_id)["version"] == refreshed["version"] + 1
        assert_builder_ledger(
            get_builder(api, world.builder_id), certified_incentive_cents=0
        )

    def test_locked_registered_file_still_accepts_a_package_issuance(self, api):
        """§2.8: "It is deliberately **not** applied to `POST /document-packages` or `POST /document-packages/{id}/issue`, because documentation packages are precisely the artefact one produces from a locked, registered file."

        §3.9: "For a **`TAX_CREDIT_45L`** package the amount is a flat tier chosen on the index alone, and `line_items` is an empty array."

        §3.9: "An index above 45 but no higher than 55 earns 100,000 cents, one thousand dollars."

        §3.9: "A successful issuance recomputes the certified variant into `certified_amount_cents` and rewrites `line_items` from the measured values, sets `status` to `ISSUED`, stamps `issued_at` from the logical clock, and raises the builder's `certified_incentive_cents` by the certified amount."

        Design: Corner/endpoints/registered_locked_file_still_accepts_package_issuance
        """
        world = build_registered_world(
            api,
            lot_number="L-7201",
            permit_date="2026-08-05",
            confirmation_number="RESNET-2026-007201",
        )
        registered = get_rating(api, world.rating_id)
        assert registered["stage"] == "REGISTERED", registered
        assert registered["file_locked"] is True, registered
        assert registered["registry_status"] == "ACCEPTED", registered
        assert_index(registered["confirmed_index"], 46)

        package = draft_package(
            api, world.rating_id, world.builder_id, "TAX_CREDIT_45L"
        )
        issued = issue_package(api, package["id"])

        assert_package_state(issued, status="ISSUED", certified_amount_cents=100000)
        assert issued["line_items"] == [], issued
        assert instant(issued["issued_at"]) == instant(CLOCK_START), issued
        assert_builder_ledger(
            get_builder(api, world.builder_id), certified_incentive_cents=100000
        )


class TestNotFoundResolution:
    @pytest.mark.parametrize(
        "route, expected_error_id",
        [
            ("builders", ERR_BUILDER_NOT_FOUND),
            ("subdivisions", ERR_SUBDIVISION_NOT_FOUND),
            ("homes", ERR_HOME_NOT_FOUND),
            ("raters", ERR_RATER_NOT_FOUND),
            ("inspections", ERR_INSPECTION_NOT_FOUND),
            ("sample-sets", ERR_SAMPLE_SET_NOT_FOUND),
            ("qa-reviews", ERR_QA_REVIEW_NOT_FOUND),
            ("corrective-actions", ERR_CORRECTIVE_ACTION_NOT_FOUND),
            ("document-packages", ERR_DOCUMENT_PACKAGE_NOT_FOUND),
        ],
    )
    def test_unknown_path_identifier_reports_the_resource_specific_code(
        self, api, route, expected_error_id
    ):
        """§2.8: "Existence of every identifier in the URL path, validated strictly left to right, so the leftmost missing identifier is the one reported."

        §2.8: "Each resource has its own not-found code: `ERR_BUILDER_NOT_FOUND`, `ERR_SUBDIVISION_NOT_FOUND`, `ERR_PLAN_MODEL_NOT_FOUND`, `ERR_HOME_NOT_FOUND`, `ERR_RATER_NOT_FOUND`, `ERR_RATING_NOT_FOUND`, `ERR_INSPECTION_NOT_FOUND`, `ERR_SAMPLE_SET_NOT_FOUND`, `ERR_QA_REVIEW_NOT_FOUND`, `ERR_CORRECTIVE_ACTION_NOT_FOUND` and `ERR_DOCUMENT_PACKAGE_NOT_FOUND`, all HTTP 404."

        §2.2: "The `message` provides a human-readable explanation of what went wrong."

        Design: Corner/errors/unknown_path_ids_return_resource_specific_not_found
        """
        readers = {
            "builders": lambda: api.get_builder(NON_EXISTENT_UUID, ADMIN_HEADERS),
            "subdivisions": lambda: api.get_subdivision(
                NON_EXISTENT_UUID, ADMIN_HEADERS
            ),
            "homes": lambda: api.get_home(NON_EXISTENT_UUID, ADMIN_HEADERS),
            "raters": lambda: api.get_rater(NON_EXISTENT_UUID, ADMIN_HEADERS),
            "inspections": lambda: api.get_inspection(
                NON_EXISTENT_UUID, ADMIN_HEADERS
            ),
            "sample-sets": lambda: api.get_sample_set(NON_EXISTENT_UUID, ADMIN_HEADERS),
            "qa-reviews": lambda: api.get_qa_review(NON_EXISTENT_UUID, ADMIN_HEADERS),
            "corrective-actions": lambda: api.submit_corrective_action(
                NON_EXISTENT_UUID,
                factories.corrective_action_submission_payload(
                    remediation_note="n/a"
                ),
                make_builder_rep_headers(NON_EXISTENT_UUID),
            ),
            "document-packages": lambda: api.issue_document_package(
                NON_EXISTENT_UUID, ADMIN_HEADERS
            ),
        }

        data = validate_error(readers[route](), expected_error_id, 404)
        assert isinstance(data["message"], str) and data["message"], data

    def test_body_foreign_keys_are_resolved_in_the_declared_input_order(self, api):
        """§2.8: "Existence of every foreign-key identifier in the request body, validated in the order the endpoint declares its inputs, yielding the same resource-specific 404 codes as step 4."

        §3.2: "Opening a **rating file** is the act of a certified rater and requires only a `home_id`, the `rater_id` of the rater of record, and — where the new file replaces a dead one — an optional `supersedes_rating_id`."

        §3.2: "A builder representative registers each lot it intends to have rated as a `Home`, supplying the `subdivision_id`, the `plan_model_id` of the plan being built on that lot, a `lot_number` unique within the subdivision, and a `permit_date` as a `YYYY-MM-DD` calendar date."

        Design: Corner/errors/body_foreign_keys_are_resolved_in_declared_input_order
        """
        builder = create_builder(api, name="Bristol Homes")
        subdivision = create_subdivision(api, builder["id"], name="Foxglove")
        rater = create_rater(api)
        plan = create_plan_model(api, subdivision["id"], rater["id"])
        home = create_home(
            api,
            subdivision["id"],
            plan["id"],
            builder["id"],
            lot_number="L-7301",
            permit_date="2026-08-05",
        )
        rater_headers = make_certified_rater_headers(rater["id"])

        both_unknown = api.create_rating(
            factories.rating_payload(NON_EXISTENT_UUID, NON_EXISTENT_UUID),
            rater_headers,
        )
        validate_error(both_unknown, ERR_HOME_NOT_FOUND, 404)

        rater_unknown = api.create_rating(
            factories.rating_payload(home["id"], NON_EXISTENT_UUID), rater_headers
        )
        validate_error(rater_unknown, ERR_RATER_NOT_FOUND, 404)

        plan_unknown = api.create_home(
            factories.home_payload(
                subdivision["id"],
                NON_EXISTENT_UUID,
                lot_number="L-7302",
                permit_date="2026-08-05",
            ),
            make_builder_rep_headers(builder["id"]),
        )
        validate_error(plan_unknown, ERR_PLAN_MODEL_NOT_FOUND, 404)

        ratings, _meta = validate_paginated(
            api.list_ratings(ADMIN_HEADERS, params={"home_id": home["id"]})
        )
        assert_count(ratings, 0)
        assert_coverage_ledger(
            get_subdivision(api, subdivision["id"]), homes_count=1
        )
