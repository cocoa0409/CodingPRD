"""Matter opening, fee-arrangement lifecycle, supersession cascade, OCC."""
from test_helpers import (
    ADMIN,
    ANALYST,
    ApiErrorId,
    add_client,
    add_matter,
    add_timekeeper,
    api_client,
    assert_fee_arrangement,
    assert_matter,
    create_matter_payload,
    create_time_entry_payload,
    draft_arrangement,
    get_matter,
    make_billing_partner_headers,
    setup_active_matter,
    setup_firm,
    submit_arrangement,
    TEST_USERS,
    validate_error,
    validate_success,
)

CLIENT_CONTACT = TEST_USERS["client_contact_headers"]


class TestMatterOpening:

    def test_matter_born_open(self):
        """PRD section 3.2: "The matter is born `OPEN`, with its
        `fee_arrangement_id` empty until an arrangement is activated."

        Design: Corner/state_machines/matter_initial_state_open
        """
        firm = setup_firm()
        tk = add_timekeeper(firm["id"])
        client = add_client(firm["id"])
        resp = api_client.create_matter(
            firm["id"], client["id"],
            create_matter_payload(responsible_partner_id=tk["id"],
                                  litigation_stage="INTAKE"),
            make_billing_partner_headers(tk["id"]))
        matter = validate_success(resp, 201)
        assert_matter(matter)
        assert matter["status"] == "OPEN", (
            f"matter must be born OPEN, got {matter['status']}")

    def test_matter_computed_fields_initialize(self):
        """PRD section 3.5: "Its `budget_total_cents` is the sum of
        `current_budget_cents` over its phase budgets in `ACTIVE` or
        `AMENDED` status — draft and voided phases never count."
        PRD section 3.5: "The signed `variance_cents` is `actual_fees_cents`
        minus `budget_total_cents`. When `budget_total_cents` is zero,
        `variance_pct_bp` is null; otherwise it is ten thousand times
        `variance_cents`, divided by `budget_total_cents`, rounded half-up
        to the nearest basis point."
        PRD section 3.5: "When `variance_pct_bp` is null,
        `variance_alert_level` is `NONE`."

        Design: Corner/entities/matter_computed_fields_initial_values
        """
        firm = setup_firm()
        tk = add_timekeeper(firm["id"])
        client = add_client(firm["id"])
        matter = add_matter(firm["id"], client["id"], tk["id"],
                            litigation_stage="INTAKE")
        assert matter["budget_total_cents"] == 0
        assert matter["actual_fees_cents"] == 0
        assert matter["variance_cents"] == 0
        assert matter["variance_pct_bp"] is None, (
            "variance_pct_bp must be null when budget_total_cents is zero")
        assert matter["variance_alert_level"] == "NONE"

    def test_matter_invalid_litigation_stage_rejected(self):
        """PRD section 3.2: "A `FirmAdmin` or `BillingPartner` opens a matter
        under a client by supplying a `matter_number` unique within that
        client, a `title`, the `litigation_stage` at which work begins — one
        of `INTAKE`, `PLEADINGS`, `DISCOVERY`, `PRETRIAL`, `TRIAL`, or
        `APPEAL` — and the `responsible_partner_id` of the timekeeper
        accountable for the budget and its write-downs." A value outside
        that list is a malformed request, rejected with the API's 400-level
        input error `ERR_INVALID_REQUEST` (PRD section 5).

        Design: Corner/entities/matter_invalid_enum_litigation_stage
        """
        firm = setup_firm()
        tk = add_timekeeper(firm["id"])
        client = add_client(firm["id"])
        resp = api_client.create_matter(
            firm["id"], client["id"],
            create_matter_payload(responsible_partner_id=tk["id"],
                                  litigation_stage="BOGUS"),
            make_billing_partner_headers(tk["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestFeeArrangementLifecycle:

    def test_activation_side_effects(self):
        """PRD section 3.2: "A successful activation stamps
        `activated_period_index` with the firm's current period, points the
        matter's `fee_arrangement_id` at the newly active arrangement,
        increments the matter's `version` by one, and — when the matter was
        still `OPEN` — automatically advances the matter to `ACTIVE`."

        Design: Corner/state_machines/fee_arrangement_activation_side_effects
        """
        firm = setup_firm()
        tk = add_timekeeper(firm["id"])
        client = add_client(firm["id"])
        matter = add_matter(firm["id"], client["id"], tk["id"])
        arrangement = draft_arrangement(firm["id"], matter["id"], "FLAT_FEE",
                                        flat_fee_cents=100000)
        submit_arrangement(firm["id"], arrangement["id"])

        matter_before = get_matter(matter["id"])
        resp = api_client.activate_fee_arrangement(
            firm["id"], arrangement["id"],
            {"expected_matter_version": matter_before["version"]},
            make_billing_partner_headers(tk["id"]))
        activated = validate_success(resp, 200)
        assert_fee_arrangement(activated)
        assert activated["status"] == "ACTIVE"
        assert activated["activated_period_index"] == 0, (
            "activation must stamp the firm's current period (0 here)")

        matter_after = get_matter(matter["id"])
        assert matter_after["status"] == "ACTIVE", (
            f"matter was OPEN and must auto-advance to ACTIVE, got "
            f"{matter_after['status']}")
        assert matter_after["fee_arrangement_id"] == arrangement["id"]
        assert matter_after["version"] == matter_before["version"] + 1

    def test_resubmit_active_arrangement_invalid(self):
        """PRD section 3.2: "`SUPERSEDED` and `REJECTED` are the
        arrangement's terminal states; an `ACTIVE` arrangement leaves that
        state only through supersession by a successor."
        PRD section 2.9: "Generic state-transition legality
        (`ERR_INVALID_STATE_TRANSITION`)."

        Design: Corner/state_machines/fee_arrangement_invalid_transition_from_active_to_draft
        """
        ctx = setup_active_matter()
        resp = api_client.submit_fee_arrangement(
            ctx["firm"]["id"], ctx["arrangement"]["id"], ANALYST)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)

    def test_flat_fee_submit_requires_flat_fee_cents(self):
        """PRD section 3.2: "The type-specific requirements are strict and
        exclusive: a `FLAT_FEE` arrangement must carry `flat_fee_cents`,
        which is null for every other type".
        PRD section 3.2: "The submission guard checks two things: the
        type-specific fields must be complete, or the request fails with
        `ERR_ARRANGEMENT_FIELDS_INCOMPLETE` (HTTP 422); and the
        one-active-or-pending rule just described must hold."

        Design: Corner/validations/arrangement_fields_incomplete_for_flat_fee
        """
        firm = setup_firm()
        tk = add_timekeeper(firm["id"])
        client = add_client(firm["id"])
        matter = add_matter(firm["id"], client["id"], tk["id"])
        arrangement = draft_arrangement(firm["id"], matter["id"], "FLAT_FEE")

        resp = api_client.submit_fee_arrangement(
            firm["id"], arrangement["id"], ANALYST)
        validate_error(resp, ApiErrorId.ERR_ARRANGEMENT_FIELDS_INCOMPLETE)

    def test_second_pending_arrangement_rejected(self):
        """PRD section 3.2: "A matter carries at most one arrangement in
        `ACTIVE` or `PENDING_APPROVAL` at any moment; attempting to create a
        second such arrangement, or to submit toward one, is rejected with
        `ERR_ARRANGEMENT_ALREADY_ACTIVE`."

        Design: Difficulty/resource_temporal_overlap/fee_arrangement_single_active_per_matter_per_fiscal_year
        """
        firm = setup_firm()
        tk = add_timekeeper(firm["id"])
        client = add_client(firm["id"])
        matter = add_matter(firm["id"], client["id"], tk["id"])

        arr1 = draft_arrangement(firm["id"], matter["id"], "FLAT_FEE",
                                 flat_fee_cents=100000)
        submit_arrangement(firm["id"], arr1["id"])
        arr2 = draft_arrangement(firm["id"], matter["id"], "CAPPED_FEE",
                                 capped_fee_cents=90000)

        resp = api_client.submit_fee_arrangement(
            firm["id"], arr2["id"], ANALYST)
        validate_error(resp, ApiErrorId.ERR_ARRANGEMENT_ALREADY_ACTIVE)



class TestSupersessionCascade:

    def _setup_two_arrangements(self):
        firm = setup_firm()
        tk = add_timekeeper(firm["id"])
        client = add_client(firm["id"])
        matter = add_matter(firm["id"], client["id"], tk["id"])
        arr1 = draft_arrangement(firm["id"], matter["id"], "FLAT_FEE",
                                 flat_fee_cents=100000)
        submit_arrangement(firm["id"], arr1["id"])
        arr1 = validate_success(api_client.activate_fee_arrangement(
            firm["id"], arr1["id"],
            {"expected_matter_version": get_matter(matter["id"])["version"]},
            make_billing_partner_headers(tk["id"])), 200)
        arr2 = draft_arrangement(
            firm["id"], matter["id"], "CAPPED_FEE", capped_fee_cents=80000,
            supersedes_arrangement_id=arr1["id"])
        submit_arrangement(firm["id"], arr2["id"])
        return firm, tk, matter, arr1, arr2

    def test_supersede_cascade_updates_prior_and_matter(self):
        """PRD section 3.2: "When the arrangement names a
        `supersedes_arrangement_id`, the referenced arrangement must
        currently be `ACTIVE`, and activation pushes that prior arrangement
        into `SUPERSEDED`."
        PRD section 3.2: "A successful activation stamps
        `activated_period_index` with the firm's current period, points the
        matter's `fee_arrangement_id` at the newly active arrangement,
        increments the matter's `version` by one, and — when the matter was
        still `OPEN` — automatically advances the matter to `ACTIVE`."

        Design: Difficulty/transitive_cascade/fee_arrangement_supersede_cascade_to_matter
        """
        firm, tk, matter, arr1, arr2 = self._setup_two_arrangements()
        resp = api_client.activate_fee_arrangement(
            firm["id"], arr2["id"],
            {"expected_matter_version": get_matter(matter["id"])["version"]},
            make_billing_partner_headers(tk["id"]))
        activated = validate_success(resp, 200)
        assert activated["status"] == "ACTIVE"

        prior = validate_success(
            api_client.get_fee_arrangement(arr1["id"], ADMIN), 200)
        assert prior["status"] == "SUPERSEDED", (
            f"prior arrangement must be SUPERSEDED, got {prior['status']}")
        matter_after = get_matter(matter["id"])
        assert matter_after["fee_arrangement_id"] == arr2["id"], (
            "matter must point at the newly active arrangement")

    def test_activate_with_stale_matter_version(self):
        """PRD section 2.7: "Activating a fee arrangement requires the
        request to carry `expected_matter_version`, the matter `version` the
        client last observed."
        PRD section 2.7: "If the supplied value does not match the matter's
        current `version` — because another writer has advanced the matter's
        version since the client last read it, for instance by activating a
        competing arrangement or by having an amendment approved — the
        request is rejected with `ERR_STALE_VERSION` (HTTP 412) and no state
        change occurs."

        Design: Corner/cross_cutting_complexity_layers/occ_stale_version_on_arrangement_activate
        """
        firm = setup_firm()
        tk = add_timekeeper(firm["id"])
        client = add_client(firm["id"])
        matter = add_matter(firm["id"], client["id"], tk["id"])
        stale_version = matter["version"]

        arr1 = draft_arrangement(firm["id"], matter["id"], "FLAT_FEE",
                                 flat_fee_cents=100000)
        submit_arrangement(firm["id"], arr1["id"])
        validate_success(api_client.activate_fee_arrangement(
            firm["id"], arr1["id"],
            {"expected_matter_version": stale_version},
            make_billing_partner_headers(tk["id"])), 200)

        arr2 = draft_arrangement(
            firm["id"], matter["id"], "CAPPED_FEE", capped_fee_cents=90000,
            supersedes_arrangement_id=arr1["id"])
        submit_arrangement(firm["id"], arr2["id"])

        # The first activation advanced the matter version, so the version
        # observed before it is stale now.
        resp = api_client.activate_fee_arrangement(
            firm["id"], arr2["id"],
            {"expected_matter_version": stale_version},
            make_billing_partner_headers(tk["id"]))
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

        unchanged = validate_success(
            api_client.get_fee_arrangement(arr2["id"], ADMIN), 200)
        assert unchanged["status"] == "PENDING_APPROVAL", (
            "no state change may occur on a stale-version rejection")


class TestMatterScopedRbac:

    def test_client_contact_cannot_create_time_entry(self):
        """PRD section 2.1: "A request whose role is not permitted for the
        target endpoint is rejected with `ERR_FORBIDDEN_FOR_ROLE`
        (HTTP 403)."
        PRD section 4: "| POST |
        `/firms/{firmId}/matters/{matterId}/time_entries` | Create a draft
        TimeEntry | Timekeeper, BillingPartner |"

        Design: Corner/rbac/client_contact_cannot_create_time_entry
        """
        firm = setup_firm()
        tk = add_timekeeper(firm["id"])
        client = add_client(firm["id"])
        matter = add_matter(firm["id"], client["id"], tk["id"],
                            litigation_stage="INTAKE")
        resp = api_client.create_time_entry(
            firm["id"], matter["id"],
            create_time_entry_payload(timekeeper_id=tk["id"],
                                      task_code="L110",
                                      litigation_stage="INTAKE"),
            CLIENT_CONTACT)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)
