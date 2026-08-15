"""Builder registration, takedown agreement lifecycle, OCC, and list filters."""
from test_helpers import (
    DEV,
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_agreement,
    create_acquired_parcel,
    create_active_agreement,
    create_agreement,
    create_builder,
    create_builder_payload,
    get_agreement,
    get_parcel,
    get_phase,
    is_valid_uuid,
    reserve_and_open_closing,
    finalize_closing,
    setup_agreement_only,
    setup_selling_scenario,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestBuilders:
    def test_builder_list_pagination(self, api):
        """PRD §2.3: "The `limit` parameter sets the maximum number of items returned: it defaults to 10 when omitted, accepts a minimum of 1, and is capped at a maximum of 100. The `offset` parameter sets how many items to skip and defaults to 0."
        PRD §2.3: "All list endpoints return resources sorted by creation timestamp in ascending order, and every list response carries `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope."

        Design: Corner/entities/builder_list_pagination
        """
        for i in (1, 2, 3):
            create_builder(builder_name=f"PB{i}", license_number=f"LIC-P{i}",
                           contact_email=f"p{i}@example.com")
        page1, meta1 = validate_paginated(
            api.list_builders(DEV, params={"limit": 2, "offset": 0}))
        assert len(page1) == 2
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True
        page2, meta2 = validate_paginated(
            api.list_builders(DEV, params={"limit": 2, "offset": 2}))
        assert len(page2) == 1
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False

    def test_duplicate_builder_license_rejected(self, api):
        """PRD §3.4: "A `DeveloperOperator` registers each homebuilder with a `builder_name`, a `license_number`, and a `contact_email`; the license number is unique across builders, and a duplicate registration is rejected with `ERR_DUPLICATE_BUILDER_LICENSE`."

        Design: Corner/validations/duplicate_builder_license_rejected
        """
        create_builder(builder_name="Dup1", license_number="LIC-DUP",
                       contact_email="d1@example.com")
        dup = api.create_builder(create_builder_payload(
            builder_name="Dup2", license_number="LIC-DUP",
            contact_email="d2@example.com"), DEV)
        validate_error(dup, ApiErrorId.ERR_DUPLICATE_BUILDER_LICENSE)
        ok = validate_success(api.create_builder(create_builder_payload(
            builder_name="Dup3", license_number="LIC-DUP-2",
            contact_email="d3@example.com"), DEV), 201)
        assert is_valid_uuid(ok["id"])


class TestAgreementLifecycle:
    def test_agreement_create_initial_state(self, api):
        """PRD §3.4: "The agreement starts in `DRAFT` with `closed_lot_count` at zero."

        Design: Corner/state_machines/agreement_create_initial_state
        """
        parcel = create_acquired_parcel(parcel_name="NP")
        builder = create_builder(builder_name="NB", license_number="LIC-N1",
                                 contact_email="n1@example.com")
        agreement = validate_success(api.create_agreement(
            {"parcel_id": parcel["id"], "builder_id": builder["id"],
             "effective_date": "2026-01-01T00:00:00Z", "base_lot_price_cents": 5000000,
             "escalator_rate_bp_per_quarter": 300, "price_cap_bp": 12000,
             "min_lots_per_quarter": 1, "scheduled_lot_count": 2}, DEV), 201)
        assert_agreement(agreement)
        assert agreement["status"] == "DRAFT"
        assert agreement["closed_lot_count"] == 0

    def test_amend_on_terminated_agreement_rejected(self, api):
        """PRD §3.7: "Termination is the hard exit — from either `ACTIVE` or `DEFAULTED` the developer may terminate the agreement into terminal `TERMINATED`, firing the same four-link lot-release cascade as a default declaration."
        PRD §3.7: "All agreement actions are state-guarded: activation requires `DRAFT`, amendment requires `ACTIVE`, default declaration requires `ACTIVE`, curing requires `DEFAULTED`, and termination requires `ACTIVE` or `DEFAULTED` — any attempt from the wrong state is rejected with `ERR_AGREEMENT_INVALID_STATE`."

        Design: Corner/state_machines/agreement_amend_from_terminated_returns_invalid_state
        """
        scenario = setup_agreement_only({"scheduled_lot_count": 2})
        agreement = scenario["agreement"]
        terminated = validate_success(api.terminate_agreement(agreement["id"], DEV))
        resp = api.amend_agreement(agreement["id"], {
            "expected_agreement_version": terminated["version"],
            "price_cap_bp": 13000,
        }, DEV)
        validate_error(resp, ApiErrorId.ERR_AGREEMENT_INVALID_STATE)

    def test_existence_beats_occ_on_missing_agreement(self, api):
        """PRD §2.8: "3. **Resource existence** — path identifiers are resolved first, in left-to-right order, followed by foreign keys carried in the request body (`parcel_id`, `builder_id`, `phase_id`, `lot_id`, `agreement_id`, `loan_id`, `provider_id`)."
        PRD §2.8: "The practical consequence of this ordering is that, for example, a request against a nonexistent parcel surfaces `ERR_PARCEL_NOT_FOUND` before any state rule is consulted, and a stale-version rejection on an extension is reported before the system even considers whether the parcel is still in `CONTINGENCY_ACTIVE`."

        Design: Corner/validations/existence_beats_occ_on_missing_agreement_returns_not_found
        """
        parcel = create_acquired_parcel(parcel_name="XP")
        resp = api.amend_agreement(NON_EXISTENT_UUID, {
            "expected_agreement_version": parcel["version"],
            "price_cap_bp": 13000,
        }, DEV)
        validate_error(resp, ApiErrorId.ERR_AGREEMENT_NOT_FOUND)

    def test_agreement_list_filters_by_status(self, api):
        """PRD §2.3: "Several list endpoints additionally accept domain filters — the parcel list filters by `status`; the phase list by `parcel_id` and `status`; the bond list by `phase_id` and `status`; the agreement list by `parcel_id`, `builder_id`, and `status`; the lot list by `phase_id`, `sales_status`, `lien_status`, and `reserved_agreement_id`; the closing list by `lot_id`, `agreement_id`, `loan_id`, and `status`; the loan list by `parcel_id` and `status`; the draw list by `loan_id` and `status`; the HOA list by `parcel_id` and `status`; the provider list by `utility_type`; and the connection list by `lot_id`, `provider_id`, and `status`."

        Design: Corner/endpoints/list_status_filter
        """
        parcel = create_acquired_parcel(parcel_name="FP2")
        builder = create_builder(builder_name="FB", license_number="LIC-F2",
                                 contact_email="f2@example.com")
        draft = create_agreement(parcel["id"], builder["id"],
                                 scheduled_lot_count=2)
        active = create_active_agreement(parcel["id"], builder["id"],
                                         base_lot_price_cents=6000000,
                                         scheduled_lot_count=2)
        rows, meta = validate_paginated(api.list_agreements(
            DEV, params={"parcel_id": parcel["id"], "status": "DRAFT"}))
        assert meta["total_count"] == 1
        assert [row["id"] for row in rows] == [draft["id"]]
        assert rows[0]["status"] == "DRAFT"
        assert active["id"] not in [row["id"] for row in rows]

    def test_occ_stale_agreement_version_rejected(self, api):
        """PRD §2.7: "Amending a takedown agreement's pricing terms requires the request to carry `expected_agreement_version` holding the client's last observed `version` of the target `TakedownAgreement`. If the agreement's current `version` has advanced since that observation — because a prior amendment or any cascade touching the agreement superseded the client's view of the pricing terms — the amendment is rejected with `ERR_STALE_AGREEMENT_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_layers/occ_stale_agreement_version_returns_412
        """
        scenario = setup_agreement_only({"scheduled_lot_count": 2})
        agreement = scenario["agreement"]
        observed_version = agreement["version"]

        amended = validate_success(api.amend_agreement(agreement["id"], {
            "expected_agreement_version": observed_version,
            "price_cap_bp": 12500,
        }, DEV))
        assert amended["version"] == observed_version + 1
        assert amended["price_cap_bp"] == 12500

        stale = api.amend_agreement(agreement["id"], {
            "expected_agreement_version": observed_version,
            "price_cap_bp": 13000,
        }, DEV)
        validate_error(stale, ApiErrorId.ERR_STALE_AGREEMENT_VERSION)
        assert get_agreement(agreement["id"])["price_cap_bp"] == 12500


class TestDefaultAndCureCycle:
    def test_declare_default_records_reason_and_state(self, api):
        """PRD §3.7: "The schedule check runs against completed quarters: declaring default on an `ACTIVE` agreement requires the agreement's `closed_lot_count` to be strictly less than the elapsed quarters since `effective_date` (computed exactly as in §3.4) multiplied by `min_lots_per_quarter`; a builder who has closed at least the scheduled number is not behind, and the attempt is rejected with `ERR_AGREEMENT_NOT_BEHIND_SCHEDULE`."
        PRD §3.7: "A successful declaration moves the agreement to `DEFAULTED`, records the supplied `reason` on `default_reason`, and fires the four-link lot-release cascade:"

        Design: Difficulty/non_linear_state_machine/agreement_default_cure_cycle
        """
        # effective 2026-01-01 at the default clock 2026-08-01 -> two elapsed
        # quarters, so 2 * min_lots_per_quarter = 4 required > 0 closed
        scenario = setup_agreement_only(
            {"min_lots_per_quarter": 2, "scheduled_lot_count": 8})
        defaulted = validate_success(api.declare_default(
            scenario["agreement"]["id"], {"reason": "missed Q2 takedown"}, DEV))
        assert defaulted["status"] == "DEFAULTED"
        assert defaulted["default_reason"] == "missed Q2 takedown"

    def test_cure_returns_active_and_clears_reason(self, api):
        """PRD §3.7: "A default need not be fatal. Curing a `DEFAULTED` agreement returns it to `ACTIVE` and clears `default_reason` to null; the request carries a `cure_note` for the record."

        Design: Difficulty/non_linear_state_machine/agreement_default_cure_cycle
        """
        scenario = setup_agreement_only(
            {"min_lots_per_quarter": 2, "scheduled_lot_count": 8})
        validate_success(api.declare_default(
            scenario["agreement"]["id"], {"reason": "missed Q2 takedown"}, DEV))
        cured = validate_success(api.cure_agreement(
            scenario["agreement"]["id"],
            {"cure_note": "builder posted cure letter"}, DEV))
        assert cured["status"] == "ACTIVE"
        assert cured["default_reason"] is None

    def test_declare_default_requires_behind_schedule(self, api):
        """PRD §3.7: "The schedule check runs against completed quarters: declaring default on an `ACTIVE` agreement requires the agreement's `closed_lot_count` to be strictly less than the elapsed quarters since `effective_date` (computed exactly as in §3.4) multiplied by `min_lots_per_quarter`; a builder who has closed at least the scheduled number is not behind, and the attempt is rejected with `ERR_AGREEMENT_NOT_BEHIND_SCHEDULE`."

        Design: Corner/errors/error_agreement_not_behind_schedule
        """
        # effective 2026-07-01 at the default clock 2026-08-01 -> one elapsed
        # month -> zero elapsed quarters -> required 0, and 0 closed is not < 0
        scenario = setup_agreement_only({
            "effective_date": "2026-07-01T00:00:00Z",
            "min_lots_per_quarter": 2,
            "scheduled_lot_count": 4,
        })
        resp = api.declare_default(
            scenario["agreement"]["id"], {"reason": "premature"}, DEV)
        validate_error(resp, ApiErrorId.ERR_AGREEMENT_NOT_BEHIND_SCHEDULE)
        assert get_agreement(scenario["agreement"]["id"])["status"] == "ACTIVE"


class TestAgreementCompletion:
    def test_agreement_auto_completes_at_scheduled_count(self, api):
        """PRD §3.4: "An agreement completes itself: when a finalize cascade (§3.5) carries `closed_lot_count` to `scheduled_lot_count` — the equality boundary triggers, so reaching exactly the scheduled count completes the agreement — an `ACTIVE` agreement auto-transitions to terminal `COMPLETED`."
        PRD §3.8: "A phase auto-completes to `SELLOUT` when every one of its recorded lots has closed, and the parcel auto-completes from `ACQUIRED` to `SOLD_OUT` when `total_lots_planned` is greater than zero and every recorded lot of the parcel has closed; both transitions fire out of the closing finalize cascade of §3.5."

        Design: Corner/cross_cutting_layers/agreement_auto_completes_at_scheduled_count_boundary
        """
        scenario = setup_selling_scenario(
            num_lots=1, agreement_overrides={"scheduled_lot_count": 1})
        closing = reserve_and_open_closing(
            scenario["lots"][0]["id"], scenario["agreement"]["id"],
            scenario["builder"]["id"])
        finalize_closing(closing["id"])

        agreement = get_agreement(scenario["agreement"]["id"])
        assert agreement["closed_lot_count"] == 1
        assert agreement["status"] == "COMPLETED"
        assert get_phase(scenario["phase"]["id"])["status"] == "SELLOUT"
        assert get_parcel(scenario["parcel"]["id"])["status"] == "SOLD_OUT"
