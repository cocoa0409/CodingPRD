"""Entry creation gates and the participation-fee calculation."""
import test_helpers as th
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId, assert_entry,
)

ENTRANT1 = th.make_entrant_headers("entrant_1")


class TestEntryCreationValidation:

    def test_create_entry_missing_org_name_rejected(self, api):
        """PRD §2.10: "required fields are present, types are valid, enum
        members are valid, numeric ranges hold (`estimated_participants` at
        least 1, `capacity` at least 1, `checklist_score` within 0 to 100
        inclusive, the end strictly after the start for time pairs), and
        conditional references are present when required — `sponsor_id` when
        the item type is `SPONSOR_READ`, `entry_id` when the item type is
        `ENTRY_INTRO` (`ERR_VALIDATION`, HTTP 400)."
        PRD §3.3: "A marching organization joins the parade when an `Entrant`
        submits an entry application carrying the organization's `org_name`, a
        `requested_category` of `FLOAT`, `BAND`, `WALKING_GROUP`, `VEHICLE`, or
        `EQUESTRIAN`, and an `estimated_participants` count of at least one."

        Design: Corner/entities/create_entry_missing_required_org_name_returns_invalid_request
        """
        parade = th.create_parade(name="Req Parade")
        payload = {"requested_category": "BAND", "estimated_participants": 10}
        resp = api.create_entry(parade["id"], payload, ENTRANT1)
        validate_error(resp, ApiErrorId.ERR_VALIDATION)

        _, meta = validate_paginated(
            api.list_entries(parade["id"], th.TEST_USERS["committee_admin_headers"])
        )
        assert meta["total_count"] == 0, "no entry may be persisted by the rejected create"

    def test_create_entry_zero_participants_rejected(self, api):
        """PRD §2.10: "required fields are present, types are valid, enum
        members are valid, numeric ranges hold (`estimated_participants` at
        least 1, `capacity` at least 1, `checklist_score` within 0 to 100
        inclusive, the end strictly after the start for time pairs), and
        conditional references are present when required — `sponsor_id` when
        the item type is `SPONSOR_READ`, `entry_id` when the item type is
        `ENTRY_INTRO` (`ERR_VALIDATION`, HTTP 400)."

        Design: Corner/entities/create_entry_zero_participants_returns_invalid_request
        """
        parade = th.create_parade(name="Zero Parade")
        payload = th.create_entry_payload(
            org_name="Nobody Marching", requested_category="WALKING_GROUP",
            estimated_participants=0,
        )
        resp = api.create_entry(parade["id"], payload, ENTRANT1)
        validate_error(resp, ApiErrorId.ERR_VALIDATION)

    def test_entry_create_after_deadline_rejected(self, api):
        """PRD §3.3: "Creation is only accepted while the logical clock reads
        at or before the parade's `entry_deadline`; a late submission is
        rejected with `ERR_ENTRY_DEADLINE_PASSED` (HTTP 422)."

        Design: Corner/validations/entry_create_after_deadline_returns_deadline_passed
        """
        parade = th.create_parade(name="Deadline Parade")
        th.set_clock("2026-06-21T00:00:00Z")
        resp = api.create_entry(
            parade["id"], th.create_entry_payload(org_name="Too Late"), ENTRANT1
        )
        validate_error(resp, ApiErrorId.ERR_ENTRY_DEADLINE_PASSED)

    def test_entry_create_exactly_at_deadline_passes(self, api):
        """PRD §3.3: "Creation is only accepted while the logical clock reads
        at or before the parade's `entry_deadline`; a late submission is
        rejected with `ERR_ENTRY_DEADLINE_PASSED` (HTTP 422)."

        Design: Corner/validations/entry_create_exactly_at_deadline_passes
        """
        parade = th.create_parade(name="Exact Deadline Parade")
        # Factory default entry_deadline is 2026-06-20T23:59:59Z.
        th.set_clock("2026-06-20T23:59:59Z")
        resp = api.create_entry(
            parade["id"], th.create_entry_payload(org_name="Just In Time"), ENTRANT1
        )
        entry = validate_success(resp, 201)
        assert_entry(entry)
        assert entry["status"] == "SUBMITTED", (
            "the exact deadline instant is on the accepting side of the gate"
        )


class TestEntryFeeCalculation:

    def test_fee_at_create_uses_requested_category_float_120(self, api):
        """PRD §3.3: "The calculation starts from a category base — 50,000
        cents for `FLOAT`, 30,000 for `BAND`, 15,000 for `WALKING_GROUP`,
        40,000 for `VEHICLE`, and 35,000 for `EQUESTRIAN` — where the category
        basis is the entry's `assigned_category` once the committee has set it
        and its `requested_category` before that."
        PRD §3.3: "The base is then grown by a participant-scaled amount
        evaluated in a pinned order: first, 300 cents for each of the first 50
        estimated participants; then 200 cents for each of the next 150,
        covering participants 51 through 200; then 100 cents for every
        participant beyond 200."

        Design: Corner/entities/entry_fee_computed_at_create_from_requested_category
        """
        parade = th.create_parade(name="Fee Parade")
        resp = api.create_entry(
            parade["id"],
            th.create_entry_payload(org_name="Fee Floats", requested_category="FLOAT",
                                    estimated_participants=120),
            ENTRANT1,
        )
        entry = validate_success(resp, 201)
        assert entry["fee_cents"] == 79000, (
            f"50000 base + 50x300 + 70x200 = 79000 at the default clock, got {entry['fee_cents']}"
        )
        assert entry["assigned_category"] is None, (
            "assigned_category stays null at create; the computation used requested_category"
        )

    def test_fee_early_band_10_no_surcharge(self, api):
        """PRD §3.3: "Finally, if the submission instant falls later than the
        instant seven days before the parade's `entry_deadline`, a late
        surcharge of twenty-five percent of the running subtotal, rounded
        half-up to whole cents, is added."
        PRD §3.3: "The submission instant used for that late branch is the
        entry's `created_at` at creation time and the current logical clock at
        resubmission time."

        Design: Corner/calculations/entry_fee_early_no_surcharge_correct_result
        """
        parade = th.create_parade(name="Early Fee Parade")
        resp = api.create_entry(
            parade["id"],
            th.create_entry_payload(org_name="Early Band", requested_category="BAND",
                                    estimated_participants=10),
            ENTRANT1,
        )
        entry = validate_success(resp, 201)
        assert entry["fee_cents"] == 33000, (
            f"30000 base + 10x300 = 33000 with the surcharge branch not taken, got {entry['fee_cents']}"
        )

    def test_fee_late_surcharge_walking_group_200(self, api):
        """PRD §3.3: "Finally, if the submission instant falls later than the
        instant seven days before the parade's `entry_deadline`, a late
        surcharge of twenty-five percent of the running subtotal, rounded
        half-up to whole cents, is added."
        PRD §3.3: "The base is then grown by a participant-scaled amount
        evaluated in a pinned order: first, 300 cents for each of the first 50
        estimated participants; then 200 cents for each of the next 150,
        covering participants 51 through 200; then 100 cents for every
        participant beyond 200."

        Design: Difficulty/combinatorial_formula/entry_fee_tiered_with_late_surcharge_branch
        """
        parade = th.create_parade(name="Late Parade")
        # 2026-06-18 is later than the 2026-06-20T23:59:59Z deadline minus 7 days.
        th.set_clock("2026-06-18T00:00:00Z")
        resp = api.create_entry(
            parade["id"],
            th.create_entry_payload(org_name="Big Walkers",
                                    requested_category="WALKING_GROUP",
                                    estimated_participants=200),
            th.make_entrant_headers("entrant_9"),
        )
        entry = validate_success(resp, 201)
        # subtotal = 15000 + 50*300 + 150*200 = 60000; surcharge = 15000.
        assert entry["fee_cents"] == 75000, (
            f"60000 subtotal + 25% late surcharge = 75000, got {entry['fee_cents']}"
        )

    def test_fee_late_surcharge_crosses_into_third_tier(self, api):
        """PRD §3.3: "The base is then grown by a participant-scaled amount
        evaluated in a pinned order: first, 300 cents for each of the first 50
        estimated participants; then 200 cents for each of the next 150,
        covering participants 51 through 200; then 100 cents for every
        participant beyond 200."
        PRD §3.3: "Finally, if the submission instant falls later than the
        instant seven days before the parade's `entry_deadline`, a late
        surcharge of twenty-five percent of the running subtotal, rounded
        half-up to whole cents, is added."

        Design: Difficulty/combinatorial_formula/entry_fee_tiered_with_late_surcharge_branch
        """
        parade = th.create_parade(name="Late Tier Parade")
        th.set_clock("2026-06-18T00:00:00Z")
        resp = api.create_entry(
            parade["id"],
            th.create_entry_payload(org_name="Huge Walkers",
                                    requested_category="WALKING_GROUP",
                                    estimated_participants=201),
            th.make_entrant_headers("entrant_9"),
        )
        entry = validate_success(resp, 201)
        assert entry["status"] == "SUBMITTED"
        # subtotal = 15000 + 15000 + 30000 + 1*100 = 60100; surcharge 15025.
        assert entry["fee_cents"] == 75125, (
            f"60100 subtotal + 25% late surcharge = 75125, got {entry['fee_cents']}"
        )
        assert entry["assigned_category"] is None

    def test_fee_recomputed_when_assigned_category_differs(self, api):
        """PRD §3.3: "Approval moves the entry to `APPROVED`, sets
        `assigned_category` from the request payload, recomputes `fee_cents` on
        the newly assigned category basis, and refreshes the parade's
        `approved_entry_count`."

        Design: Corner/cross_cutting_layers/fee_recomputed_when_assigned_category_differs
        """
        committee = th.TEST_USERS["committee_admin_headers"]
        parade = th.create_parade(name="Recat Parade")
        entry = th.create_entry(
            parade["id"], "entrant_1", org_name="Recat Floats",
            requested_category="FLOAT", estimated_participants=120,
        )
        assert entry["fee_cents"] == 79000, "FLOAT basis before approval"
        th.get_success_data(api.start_review(entry["id"], committee))
        approved = validate_success(
            api.approve_entry(entry["id"], {"assigned_category": "VEHICLE"}, committee)
        )
        assert approved["assigned_category"] == "VEHICLE"
        assert approved["fee_cents"] == 69000, (
            f"VEHICLE base 40000 + 50x300 + 70x200 = 69000, got {approved['fee_cents']}"
        )


class TestEntryListing:

    def test_entries_list_pagination_envelope(self, api):
        """PRD §2.3: "The `meta` object of a list response carries `limit`,
        `offset`, `total_count`, and `has_more`."
        PRD §2.3: "The `limit` parameter sets the maximum number of items
        returned; it defaults to 10, with a minimum of 1 and a maximum of 100."

        Design: Corner/entities/entries_list_pagination_envelope
        """
        committee = th.TEST_USERS["committee_admin_headers"]
        parade = th.create_parade(name="Page Parade")
        for i, org in enumerate(("Page One", "Page Two", "Page Three"), start=1):
            th.create_entry(parade["id"], f"entrant_{i}", org_name=org,
                            estimated_participants=9 + i)

        data, meta = validate_paginated(
            api.list_entries(parade["id"], committee, params={"limit": 2, "offset": 0})
        )
        assert len(data) == 2, f"limit 2 must return exactly 2 items, got {len(data)}"
        assert meta["total_count"] == 3
        assert meta["has_more"] is True
        assert meta["limit"] == 2 and meta["offset"] == 0
