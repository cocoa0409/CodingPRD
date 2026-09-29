"""Identity and authorization, optimistic concurrency and read-your-write."""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories
from test_helpers.api_errors import (
    ERR_FORBIDDEN_ROLE,
    ERR_NOT_RESOURCE_OWNER,
    ERR_STALE_RATING_VERSION,
    ERR_STALE_SAMPLE_SET_VERSION,
    ERR_UNAUTHENTICATED,
)
from test_helpers.assertions import (
    assert_builder_ledger,
    assert_count,
    assert_coverage_ledger,
    assert_home_sampling_state,
    assert_package_state,
    assert_rater_standing,
    assert_sample_set_counters,
)
from test_helpers.fixtures import (
    build_confirmed_world,
    create_builder,
    create_home,
    create_plan_model,
    create_rater,
    create_sample_set,
    create_subdivision,
    get_builder,
    get_home,
    get_rater,
    get_rating,
    get_sample_set,
    get_subdivision,
    list_packages,
)
from test_helpers.test_users import (
    ADMIN_HEADERS,
    make_builder_rep_headers,
    make_certified_rater_headers,
)

#: A request that carries neither `X-User-ID` nor `X-User-Role` (§2.1).
ANONYMOUS_HEADERS = {"Content-Type": "application/json"}


class TestRoleAuthorization:
    def test_builder_rep_cannot_certify_a_rater(self, api):
        """§2.1: "Once authentication succeeds, the acting role must appear on the authorization list of the endpoint being called (see §4); a role calling an endpoint it is not listed on is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."

        §2.11: "A newly certified person starts with `certification_status` of `ACTIVE`, an `effective_certification_status` derived immediately against the logical clock, `qa_failure_count`, `confirmed_rating_count`, `qa_completed_count` and `qa_files_owed` all at zero, and `registry_hold` false."

        Design: Corner/rbac/builder_rep_cannot_certify_a_rater
        """
        builder = create_builder(api, name="Bristol Homes")
        payload = factories.rater_payload(
            full_name="Rae Tarrant",
            cert_level="RATER",
            cert_expires_at="2027-06-30T00:00:00Z",
        )

        refused = api.create_rater(payload, make_builder_rep_headers(builder["id"]))
        refused_body = validate_error(refused, ERR_FORBIDDEN_ROLE, 403)
        assert "id" not in refused_body, refused_body

        allowed = validate_success(api.create_rater(payload, ADMIN_HEADERS), 201)
        assert allowed["cert_level"] == "RATER", allowed
        assert_rater_standing(
            get_rater(api, allowed["id"]),
            certification_status="ACTIVE",
            effective_certification_status="ACTIVE",
            qa_failure_count=0,
        )

    def test_request_without_a_role_header_is_unauthenticated(self, api):
        """§2.1: "Every request must carry two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which that user is acting."

        §2.1: "If `X-User-Role` is absent or is not one of those five strings, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

        §3.1: "A newly registered builder has `status` of `ACTIVE`, and its four derived numbers — `open_corrective_action_count`, `revoked_package_count`, `certified_incentive_cents` and the `sampling_eligible` flag — are computed immediately, which for a brand-new builder means `open_corrective_action_count`, `revoked_package_count` and `certified_incentive_cents` all read zero."

        Design: Corner/rbac/request_with_no_role_header_is_unauthenticated
        """
        payload = factories.builder_payload(
            name="Bristol Homes",
            builder_type="PRODUCTION",
            utility_program_budget_cents=250000,
        )

        anonymous = api.create_builder(payload, ANONYMOUS_HEADERS)
        anonymous_body = validate_error(anonymous, ERR_UNAUTHENTICATED, 401)
        assert "id" not in anonymous_body, anonymous_body

        allowed = validate_success(api.create_builder(payload, ADMIN_HEADERS), 201)
        assert_builder_ledger(
            get_builder(api, allowed["id"]),
            status="ACTIVE",
            certified_incentive_cents=0,
        )

    def test_rep_of_another_builder_cannot_register_a_home(self, api):
        """§2.1: "When `X-User-Role` is `BuilderRep`, `X-User-ID` is the `id` of the acting `Builder` row. Ownership checks resolve the target resource up through the home and its subdivision to the owning builder and compare that builder's `id` to `X-User-ID`: a builder representative registers lots only in its own subdivisions, answers only corrective actions raised against its own ratings, and drafts documentation packages only against its own homes' ratings."

        §2.1: "An identity-bearing actor that operates on a resource which does not resolve to its own `X-User-ID` is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."

        Design: Corner/rbac/rep_of_another_builder_cannot_register_a_home
        """
        owner = create_builder(api, name="Bristol Homes")
        stranger = create_builder(api, name="Cardinal Homes")
        subdivision = create_subdivision(api, owner["id"], name="Foxglove")
        rater = create_rater(api)
        plan = create_plan_model(api, subdivision["id"], rater["id"])
        payload = factories.home_payload(
            subdivision["id"],
            plan["id"],
            lot_number="L-7401",
            permit_date="2026-08-05",
        )

        refused = api.create_home(payload, make_builder_rep_headers(stranger["id"]))
        validate_error(refused, ERR_NOT_RESOURCE_OWNER, 403)

        allowed = validate_success(
            api.create_home(payload, make_builder_rep_headers(owner["id"])), 201
        )
        assert allowed["subdivision_id"] == subdivision["id"], allowed
        assert_coverage_ledger(
            get_subdivision(api, subdivision["id"]), homes_count=1
        )


class TestOptimisticConcurrency:
    def test_stale_expected_rating_version_blocks_a_second_draft(self, api):
        """§2.9: "`POST /document-packages` requires `expected_rating_version` matching the current `version` of the `Rating` named by `rating_id`."

        §2.9: "If the rating's `version` has advanced since the client last read it, the draft is rejected with `ERR_STALE_RATING_VERSION` (HTTP 412)."

        §2.9: "A successful draft itself increases the rating's `version` by 1, which means a client wishing to draft twice in a row must re-read the rating in between."

        Design: Corner/cross_cutting_layers/stale_expected_rating_version_on_package_draft_rejected
        """
        world = build_confirmed_world(
            api, lot_number="L-7501", permit_date="2026-08-05"
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

        stale = api.create_document_package(
            factories.document_package_payload(
                world.rating_id,
                version_at_confirmation,
                package_type="UTILITY_PROGRAM",
            ),
            world.rep_headers,
        )
        validate_error(stale, ERR_STALE_RATING_VERSION, 412)

        refreshed = get_rating(api, world.rating_id)
        assert refreshed["version"] == version_at_confirmation + 1, refreshed
        retried = validate_success(
            api.create_document_package(
                factories.document_package_payload(
                    world.rating_id,
                    refreshed["version"],
                    package_type="UTILITY_PROGRAM",
                ),
                world.rep_headers,
            ),
            201,
        )

        packages = {item["id"]: item for item in list_packages(api, world.rating_id)}
        assert_count(list(packages), 2)
        assert_package_state(packages[first["id"]], status="DRAFT")
        assert_package_state(
            packages[retried["id"]], status="DRAFT", provisional_amount_cents=132500
        )
        assert packages[retried["id"]]["package_type"] == "UTILITY_PROGRAM", packages

    def test_stale_expected_sample_set_version_blocks_a_second_membership_add(self, api):
        """§2.9: "`POST /sample-sets/{id}/homes` requires `expected_sample_set_version` matching the target `SampleSet`'s current `version`; a mismatch is `ERR_STALE_SAMPLE_SET_VERSION` (HTTP 412)."

        §2.9: "A successful addition increases the set's `version` by 1."

        Design: Corner/cross_cutting_layers/stale_expected_sample_set_version_on_membership_add_rejected
        """
        builder = create_builder(api, name="Bristol Homes")
        subdivision = create_subdivision(
            api, builder["id"], name="Foxglove", sampling_enabled=True
        )
        rater = create_rater(api)
        plan = create_plan_model(api, subdivision["id"], rater["id"])
        first_home = create_home(
            api,
            subdivision["id"],
            plan["id"],
            builder["id"],
            lot_number="L-7601",
            permit_date="2026-08-05",
        )
        second_home = create_home(
            api,
            subdivision["id"],
            plan["id"],
            builder["id"],
            lot_number="L-7602",
            permit_date="2026-08-06",
        )
        sample_set = create_sample_set(
            api,
            subdivision["id"],
            rater["id"],
            window_start_date="2026-08-01",
            window_end_date="2026-08-31",
        )
        version_at_creation = sample_set["version"]
        rater_headers = make_certified_rater_headers(rater["id"])
        validate_success(
            api.add_sample_set_home(
                sample_set["id"],
                factories.sample_set_membership_payload(
                    first_home["id"], version_at_creation
                ),
                rater_headers,
            ),
            201,
        )

        stale = api.add_sample_set_home(
            sample_set["id"],
            factories.sample_set_membership_payload(
                second_home["id"], version_at_creation
            ),
            rater_headers,
        )
        validate_error(stale, ERR_STALE_SAMPLE_SET_VERSION, 412)

        after_rejection = get_sample_set(api, sample_set["id"])
        assert_sample_set_counters(after_rejection, member_count=1)
        assert after_rejection["version"] == version_at_creation + 1, after_rejection

        validate_success(
            api.add_sample_set_home(
                sample_set["id"],
                factories.sample_set_membership_payload(
                    second_home["id"], after_rejection["version"]
                ),
                rater_headers,
            ),
            201,
        )

        assert_sample_set_counters(
            get_sample_set(api, sample_set["id"]), member_count=2
        )
        assert_home_sampling_state(
            get_home(api, second_home["id"]), sample_set_id=sample_set["id"]
        )
        assert_coverage_ledger(
            get_subdivision(api, subdivision["id"]),
            sampled_home_count=2,
            unsampled_home_count=0,
        )


class TestImmediateConsistency:
    def test_coverage_ledger_is_visible_on_the_very_next_read(self, api):
        """§2.10: "Every hop of every cascade is mandatory and runs in the same request as the operation that triggered it: there is no deferred or eventual reconciliation anywhere in this API."

        §3.5: "A successful addition writes the set's identifier into the home's `sample_set_id`, moves the home's `sampling_role` from `UNASSIGNED` to `MEMBER`, raises the set's `member_count`, and re-derives the subdivision's coverage ledger so that `sampled_home_count` rises by one and `unsampled_home_count` falls by one."

        §2.10: "Membership is always read from the home's own `sample_set_id`, never from a sample set's `member_count`."

        Design: Corner/consistency_model/coverage_ledger_is_visible_immediately_after_the_write
        """
        builder = create_builder(api, name="Bristol Homes")
        subdivision = create_subdivision(
            api, builder["id"], name="Foxglove", sampling_enabled=True
        )
        rater = create_rater(api)
        plan = create_plan_model(api, subdivision["id"], rater["id"])
        joining_home = create_home(
            api,
            subdivision["id"],
            plan["id"],
            builder["id"],
            lot_number="L-7701",
            permit_date="2026-08-05",
        )
        untouched_home = create_home(
            api,
            subdivision["id"],
            plan["id"],
            builder["id"],
            lot_number="L-7702",
            permit_date="2026-08-06",
        )
        sample_set = create_sample_set(
            api,
            subdivision["id"],
            rater["id"],
            window_start_date="2026-08-01",
            window_end_date="2026-08-31",
        )

        validate_success(
            api.add_sample_set_home(
                sample_set["id"],
                factories.sample_set_membership_payload(
                    joining_home["id"], sample_set["version"]
                ),
                make_certified_rater_headers(rater["id"]),
            ),
            201,
        )

        assert_home_sampling_state(
            get_home(api, joining_home["id"]),
            sampling_role="MEMBER",
            sample_set_id=sample_set["id"],
        )
        assert_coverage_ledger(
            get_subdivision(api, subdivision["id"]),
            homes_count=2,
            sampled_home_count=1,
            unsampled_home_count=1,
        )
        stored_set = get_sample_set(api, sample_set["id"])
        assert_sample_set_counters(stored_set, member_count=1)
        assert stored_set["version"] == 2, stored_set
        assert_home_sampling_state(
            get_home(api, untouched_home["id"]),
            sampling_role="UNASSIGNED",
            sample_set_id=None,
        )
        members, _meta = validate_paginated(
            api.list_homes(ADMIN_HEADERS, params={"sample_set_id": sample_set["id"]})
        )
        assert_count(members, 1)
