"""Customer accounts, artwork revision registration, and the revision loop."""
from test_helpers import (
    EST,
    NON_EXISTENT_UUID,
    PREPRESS,
    api_client,
    approve_job,
    assert_artwork_version,
    assert_customer,
    create_customer,
    create_job_for,
    is_valid_uuid,
    register_artwork,
    setup_plant,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestCustomerAccounts:

    def test_customer_create_applies_defaults(self):
        """PRD §3.1: "An `Estimator` opens the commercial relationship by
        registering a customer with an `account_name`. Two optional attributes
        complete the account: `credit_hold` (default false) marks accounts that
        must not release new work to press, and `preferred_currency` (default
        `USD`) records the billing currency code."
        PRD §2.4: "Every resource is identified by an `id`, a server-minted
        UUID with no type prefix."

        Design: Corner/entities/customer_create_applies_defaults
        """
        resp = api_client.create_customer({"account_name": "Default Co"}, EST)
        customer = validate_success(resp, 201)
        assert_customer(customer)
        assert is_valid_uuid(customer["id"])
        assert customer["credit_hold"] is False
        assert customer["preferred_currency"] == "USD"
        assert customer["version"] == 1

    def test_customer_not_found_returns_404(self):
        """PRD §2.5: "Identifiers embedded in the URL are resolved strictly
        left to right — customer before job, job before measurement, roll or
        letter — and the first identifier that does not resolve to an existing
        resource is rejected with `ERR_NOT_FOUND`; deeper identifiers are never
        examined."

        Design: Corner/entities/customer_not_found_returns_404
        """
        resp = api_client.get_customer(NON_EXISTENT_UUID, EST)
        validate_error(resp, "ERR_NOT_FOUND", expected_status=404)

    def test_customer_list_pagination_envelope(self):
        """PRD §2.3: "Endpoints that return lists of resources accept two query
        parameters. `limit` sets the maximum number of items returned: it
        defaults to 10, with a minimum of 1 and a maximum of 100. `offset` sets
        the number of items to skip and defaults to 0."
        PRD §2.3: "The `meta` object of a list response carries the pagination
        fields `limit`, `offset`, `total_count` and `has_more`."

        Design: Corner/entities/customer_list_pagination_envelope
        """
        for name in ("Page A", "Page B", "Page C"):
            validate_success(
                api_client.create_customer({"account_name": name}, EST), 201)

        data, meta = validate_paginated(
            api_client.list_customers(EST, params={"limit": 2, "offset": 0}))
        assert len(data) == 2, f"expected 2 items, got {len(data)}"
        assert meta["total_count"] == 3
        assert meta["has_more"] is True
        assert meta["limit"] == 2
        assert meta["offset"] == 0


class TestArtworkRevisionRegistration:

    def test_artwork_revision_must_increase_monotonically(self):
        """PRD §3.3: "Revision numbers are strictly monotonic within an artwork
        code: registration is rejected with
        `ERR_ARTWORK_REVISION_NOT_MONOTONIC` unless the new `revision_no` is
        strictly greater than the current maximum revision number registered
        for the same customer and `artwork_code`. A new revision is born
        `DRAFT`."

        Design: Corner/entities/artwork_revision_must_increase_monotonically
        """
        customer = create_customer(account_name="Rev Co")
        rev1 = validate_success(api_client.create_artwork_version(
            customer["id"],
            {"artwork_code": "AW-R", "revision_no": 1, "color_count": 2,
             "plate_set_cost_cents": 100000},
            PREPRESS), 201)
        assert_artwork_version(rev1)
        assert rev1["status"] == "DRAFT"

        dup = api_client.create_artwork_version(
            customer["id"],
            {"artwork_code": "AW-R", "revision_no": 1, "color_count": 2,
             "plate_set_cost_cents": 100000},
            PREPRESS)
        validate_error(dup, "ERR_ARTWORK_REVISION_NOT_MONOTONIC",
                       expected_status=422)

        rev2 = validate_success(api_client.create_artwork_version(
            customer["id"],
            {"artwork_code": "AW-R", "revision_no": 2, "color_count": 2,
             "plate_set_cost_cents": 100000},
            PREPRESS), 201)
        assert rev2["status"] == "DRAFT"
        assert rev2["revision_no"] == 2

    def test_artwork_list_reverse_reachability(self):
        """PRD §3.3: "A `PrepressOperator` registers each revision under its
        owning customer — the system records the linkage as the revision's
        `customer_id` — supplying an `artwork_code` that is unique per
        customer, a `revision_no`, the `color_count` of print stations the art
        requires (between 1 and 8 inclusive), and the one-time
        `plate_set_cost_cents` for that revision's plate set."
        PRD §4: GET `/label-jobs/customers/{id}/artwork-versions` — "List a
        customer's artwork revisions".

        Design: Corner/entities/artwork_list_reverse_reachability
        """
        customer = create_customer(account_name="List Co")
        a1 = validate_success(api_client.create_artwork_version(
            customer["id"],
            {"artwork_code": "AW-LA", "revision_no": 1, "color_count": 1,
             "plate_set_cost_cents": 50000},
            PREPRESS), 201)
        a2 = validate_success(api_client.create_artwork_version(
            customer["id"],
            {"artwork_code": "AW-LB", "revision_no": 1, "color_count": 2,
             "plate_set_cost_cents": 70000},
            PREPRESS), 201)

        data, meta = validate_paginated(
            api_client.list_artwork_versions(customer["id"], PREPRESS))
        ids = {row["id"] for row in data}
        assert ids == {a1["id"], a2["id"]}, \
            f"expected exactly the customer's two revisions, got {ids}"
        assert meta["total_count"] == 2


class TestArtworkRevisionLoop:

    def test_revision_loop_submit_return_resubmit_approve(self):
        """PRD §3.3: "The revision loop is a prepress affair. Submitting a
        revision moves it `DRAFT` → `SUBMITTED`, and submitting anything that
        is not `DRAFT` draws `ERR_ARTWORK_NOT_DRAFT`. From `SUBMITTED` there
        are two exits: approval moves the revision to `APPROVED`, while
        returning it for rework moves it back to `DRAFT`; both require the
        revision to currently be `SUBMITTED`, else
        `ERR_ARTWORK_NOT_SUBMITTED`. Submit, approve and return each increment
        the revision's `version`."

        Design: Difficulty/non_linear_state_machine/artwork_revision_submit_return_cycle
        """
        customer = create_customer(account_name="Cycle Co")
        artwork = validate_success(api_client.create_artwork_version(
            customer["id"],
            {"artwork_code": "AW-5", "revision_no": 1, "color_count": 3,
             "plate_set_cost_cents": 90000},
            PREPRESS), 201)
        assert artwork["status"] == "DRAFT"

        artwork = validate_success(
            api_client.submit_artwork(customer["id"], artwork["id"], PREPRESS))
        assert artwork["status"] == "SUBMITTED"
        artwork = validate_success(
            api_client.return_artwork(customer["id"], artwork["id"], PREPRESS))
        assert artwork["status"] == "DRAFT"
        artwork = validate_success(
            api_client.submit_artwork(customer["id"], artwork["id"], PREPRESS))
        assert artwork["status"] == "SUBMITTED"
        artwork = validate_success(
            api_client.approve_artwork(customer["id"], artwork["id"], PREPRESS))
        assert artwork["status"] == "APPROVED", \
            "DRAFT→SUBMITTED→DRAFT→SUBMITTED→APPROVED loop must succeed"

    def test_revision_loop_version_increments_each_hop(self):
        """PRD §3.3: "Submit, approve and return each increment the revision's
        `version`."
        PRD §2.4: "Alongside it, resources carry `created_at` and `updated_at`
        — ISO 8601 UTC timestamps with three fractional digits (for example,
        `2025-05-24T10:30:00.123Z`) — and an integer `version` that increments
        by one on every mutation of the resource, whether the mutation is
        client-invoked or server-driven."

        Design: Difficulty/non_linear_state_machine/artwork_revision_submit_return_cycle
        """
        customer = create_customer(account_name="Cycle Ver Co")
        artwork = validate_success(api_client.create_artwork_version(
            customer["id"],
            {"artwork_code": "AW-5V", "revision_no": 1, "color_count": 3,
             "plate_set_cost_cents": 90000},
            PREPRESS), 201)
        assert artwork["version"] == 1

        artwork = validate_success(
            api_client.submit_artwork(customer["id"], artwork["id"], PREPRESS))
        assert artwork["version"] == 2
        artwork = validate_success(
            api_client.return_artwork(customer["id"], artwork["id"], PREPRESS))
        assert artwork["version"] == 3
        artwork = validate_success(
            api_client.submit_artwork(customer["id"], artwork["id"], PREPRESS))
        assert artwork["version"] == 4
        artwork = validate_success(
            api_client.approve_artwork(customer["id"], artwork["id"], PREPRESS))
        assert artwork["version"] == 5, \
            "create=1 plus four transitions must land on version 5"

    def test_artwork_submit_twice_rejected(self):
        """PRD §3.3: "Submitting a revision moves it `DRAFT` → `SUBMITTED`,
        and submitting anything that is not `DRAFT` draws
        `ERR_ARTWORK_NOT_DRAFT`."

        Design: Corner/state_machines/artwork_submit_twice_rejected
        """
        customer = create_customer(account_name="Sub Co")
        artwork = validate_success(api_client.create_artwork_version(
            customer["id"],
            {"artwork_code": "AW-SU", "revision_no": 1, "color_count": 2,
             "plate_set_cost_cents": 120000},
            PREPRESS), 201)
        validate_success(
            api_client.submit_artwork(customer["id"], artwork["id"], PREPRESS))

        resp = api_client.submit_artwork(customer["id"], artwork["id"],
                                         PREPRESS)
        validate_error(resp, "ERR_ARTWORK_NOT_DRAFT", expected_status=409)

    def test_artwork_approve_after_approved_rejected(self):
        """PRD §3.3: "From `SUBMITTED` there are two exits: approval moves the
        revision to `APPROVED`, while returning it for rework moves it back to
        `DRAFT`; both require the revision to currently be `SUBMITTED`, else
        `ERR_ARTWORK_NOT_SUBMITTED`."
        PRD §3.3: "`APPROVED` and `OBSOLETE` are the terminal states of an
        artwork revision."

        Design: Corner/state_machines/artwork_approve_after_approved_rejected
        """
        customer = create_customer(account_name="Term Co")
        artwork = register_artwork(customer["id"], artwork_code="AW-TE",
                                   revision_no=1, color_count=2,
                                   plate_set_cost_cents=120000)
        assert artwork["status"] == "APPROVED"

        resp = api_client.approve_artwork(customer["id"], artwork["id"],
                                          PREPRESS)
        validate_error(resp, "ERR_ARTWORK_NOT_SUBMITTED", expected_status=409)

        reread = validate_success(
            api_client.get_artwork_version(customer["id"], artwork["id"],
                                           PREPRESS))
        assert reread["status"] == "APPROVED"


class TestJobApproval:

    def test_job_approve_twice_rejected(self):
        """PRD §3.4: "An `Estimator` then approves the quote, moving the job
        from `QUOTED` to `APPROVED` — any other starting state draws
        `ERR_JOB_NOT_QUOTED` — and incrementing the job's `version`."

        Design: Corner/state_machines/job_approve_twice_rejected
        """
        plant = setup_plant(account_name="Twice Co", artwork_code="AW-T")
        job = create_job_for(plant, quantity_ordered=1000)
        approved = approve_job(job["id"])
        assert approved["status"] == "APPROVED"

        resp = api_client.approve_job(job["id"], EST)
        validate_error(resp, "ERR_JOB_NOT_QUOTED", expected_status=409)

        reread = validate_success(api_client.get_job(job["id"], EST))
        assert reread["status"] == "APPROVED", \
            "rejected second approve must not move the job"
