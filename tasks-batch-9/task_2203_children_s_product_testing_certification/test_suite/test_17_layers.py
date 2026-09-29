"""Cross-cutting layers: the two optimistic-concurrency guards and derived-state discipline."""

from test_helpers import (
    ApiErrorId,
    factories,
    fixtures as fx,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.test_users import ADMIN_HEADERS, COORDINATOR_HEADERS, OFFICER_HEADERS

STARTUP_CLOCK = "2026-08-01T00:00:00Z"


def _certificate_count(api, product_id):
    """How many certificate rows the product carries right now."""
    _, meta = validate_paginated(
        api.list_certificates({"product_id": product_id}, headers=ADMIN_HEADERS)
    )
    return meta["total_count"]


class TestCertificateCreateGuardsTheProductVersion:
    """Drafting a certificate is gated on the exact product version the client saw."""

    def test_a_matching_version_is_accepted_and_recorded_on_the_draft(self, api):
        """PRD 3.7: "The submitted `expected_product_version` is retained as
        `expected_product_version_seen`, and the product's own `version` increments by 1 because
        drafting a certificate against it is a compliance-relevant event."

        Design: Corner/cross_cutting_complexity_layers/corner_layers_optimistic_concurrency_certificate_create_guards_the_supersession_pointer
        """
        fx.set_clock(api, STARTUP_CLOCK)
        env = fx.evidence_complete_env(api)
        product_before = fx.get_product(api, env["product"]["id"])
        assert product_before["compliance_posture"] == "CLEARED"

        certificate = validate_success(
            api.draft_certificate(
                product_before["id"],
                factories.certificate_payload(product_before["version"]),
                headers=OFFICER_HEADERS,
            ),
            201,
        )
        assert certificate["expected_product_version_seen"] == product_before["version"]
        assert certificate["supersedes_certificate_id"] is None
        assert certificate["issuance_status"] == "DRAFT"

        product_after = fx.get_product(api, product_before["id"])
        assert product_after["version"] == product_before["version"] + 1

    def test_replaying_the_same_version_after_the_guarded_write_is_refused(self, api):
        """PRD 2.6: "If that value does not equal the product's current `version`, the request is
        rejected with `ERR_STALE_PRODUCT_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_complexity_layers/corner_layers_optimistic_concurrency_certificate_create_guards_the_supersession_pointer
        """
        fx.set_clock(api, STARTUP_CLOCK)
        env = fx.evidence_complete_env(api)
        product_id = env["product"]["id"]
        stale_version = fx.get_product(api, product_id)["version"]
        fx.draft_certificate(api, product_id, stale_version)
        assert _certificate_count(api, product_id) == 1

        validate_error(
            api.draft_certificate(
                product_id,
                factories.certificate_payload(stale_version),
                headers=OFFICER_HEADERS,
            ),
            ApiErrorId.STALE_PRODUCT_VERSION.value,
            412,
        )
        assert _certificate_count(api, product_id) == 1

    def test_re_reading_the_product_lets_the_retry_through(self, api):
        """PRD 3.7: "`supersedes_certificate_id` is set to the `id` of the product's currently
        issued certificate, or null when the product has none" — the first draft was never
        issued, so the retry still supersedes nothing.

        Design: Corner/cross_cutting_complexity_layers/corner_layers_optimistic_concurrency_certificate_create_guards_the_supersession_pointer
        """
        fx.set_clock(api, STARTUP_CLOCK)
        env = fx.evidence_complete_env(api)
        product_id = env["product"]["id"]
        first = fx.draft_certificate(api, product_id, fx.get_product(api, product_id)["version"])

        fresh_version = fx.get_product(api, product_id)["version"]
        second = validate_success(
            api.draft_certificate(
                product_id,
                factories.certificate_payload(fresh_version),
                headers=OFFICER_HEADERS,
            ),
            201,
        )
        assert second["expected_product_version_seen"] == fresh_version
        assert second["supersedes_certificate_id"] is None
        assert fx.get_certificate(api, first["id"])["issuance_status"] == "DRAFT"
        assert _certificate_count(api, product_id) == 2

    def test_the_guard_field_is_required_and_is_an_equality_not_a_lower_bound(self, api):
        """PRD 2.6: "Drafting a children's product certificate against a product requires
        `expected_product_version` as a non-optional field of the request body, carrying the
        `version` of the `Product` the client last read. If that value does not equal the
        product's current `version`, the request is rejected with `ERR_STALE_PRODUCT_VERSION`
        (HTTP 412)."

        Design: Corner/cross_cutting_complexity_layers/corner_layers_optimistic_concurrency_certificate_create_guards_the_supersession_pointer
        """
        fx.set_clock(api, STARTUP_CLOCK)
        env = fx.evidence_complete_env(api)
        product_id = env["product"]["id"]
        current_version = fx.get_product(api, product_id)["version"]

        without_guard = factories.certificate_payload(current_version)
        del without_guard["expected_product_version"]
        validate_error(
            api.draft_certificate(product_id, without_guard, headers=OFFICER_HEADERS),
            ApiErrorId.INVALID_REQUEST.value,
            400,
        )
        validate_error(
            api.draft_certificate(
                product_id,
                factories.certificate_payload(current_version + 1),
                headers=OFFICER_HEADERS,
            ),
            ApiErrorId.STALE_PRODUCT_VERSION.value,
            412,
        )
        assert _certificate_count(api, product_id) == 0
        validate_success(
            api.draft_certificate(
                product_id,
                factories.certificate_payload(current_version),
                headers=OFFICER_HEADERS,
            ),
            201,
        )


def _retest_passed_case(api):
    """A case carried to RETEST_PASSED through one stop-distribution and one passing retest."""
    env = fx.retest_case_env(api)
    retest_order_id = env["case"]["active_retest_order_id"]
    fx.start_order(api, retest_order_id, env["laboratory"]["id"])
    fx.report(api, retest_order_id, env["laboratory"]["id"], 10)
    env["case"] = fx.get_case(api, env["case"]["id"])
    return env


class TestCorrectiveActionGuardsTheCaseRevision:
    """Filing a corrective action is gated on the exact case version the client saw."""

    def test_the_first_filed_plan_sets_the_reference_and_the_first_revision(self, api):
        """PRD 3.9: "From `RETEST_PASSED` the case moves to `CORRECTIVE_ACTION_APPROVED`, storing
        `corrective_action_ref` and incrementing `corrective_action_revision` by 1."

        Design: Corner/cross_cutting_complexity_layers/corner_layers_optimistic_concurrency_corrective_action_guards_the_revision_counter
        """
        fx.set_clock(api, STARTUP_CLOCK)
        env = _retest_passed_case(api)
        case = env["case"]
        assert case["case_state"] == "RETEST_PASSED"
        assert case["corrective_action_revision"] == 0

        filed = validate_success(
            api.file_corrective_action(
                case["id"],
                {
                    "expected_case_version": case["version"],
                    "corrective_action_ref": "CAP-2026-0041",
                },
                headers=OFFICER_HEADERS,
            ),
            200,
        )
        assert filed["case_state"] == "CORRECTIVE_ACTION_APPROVED"
        assert filed["corrective_action_ref"] == "CAP-2026-0041"
        assert filed["corrective_action_revision"] == 1
        assert filed["version"] == case["version"] + 1

    def test_a_stale_case_version_neither_replaces_the_plan_nor_moves_the_counter(self, api):
        """PRD 3.9: "The submitted `expected_case_version` must equal the case's stored `version`
        or the request is refused with `ERR_STALE_CASE_VERSION` and HTTP 412, as set out in §2.6."

        Design: Corner/cross_cutting_complexity_layers/corner_layers_optimistic_concurrency_corrective_action_guards_the_revision_counter
        """
        fx.set_clock(api, STARTUP_CLOCK)
        env = _retest_passed_case(api)
        case_id = env["case"]["id"]
        stale_version = env["case"]["version"]
        fx.file_corrective_action(api, case_id, stale_version, ref="CAP-2026-0041")

        validate_error(
            api.file_corrective_action(
                case_id,
                {
                    "expected_case_version": stale_version,
                    "corrective_action_ref": "CAP-2026-0042",
                },
                headers=OFFICER_HEADERS,
            ),
            ApiErrorId.STALE_CASE_VERSION.value,
            412,
        )
        unchanged = fx.get_case(api, case_id)
        assert unchanged["corrective_action_ref"] == "CAP-2026-0041"
        assert unchanged["corrective_action_revision"] == 1

    def test_the_counter_rises_only_on_accepted_writes(self, api):
        """PRD 3.9: "From `CORRECTIVE_ACTION_APPROVED` the same call self-loops on
        `CORRECTIVE_ACTION_APPROVED`, replacing `corrective_action_ref` with the newly submitted
        reference — superseding the prior plan — and again incrementing
        `corrective_action_revision` by 1."

        Design: Corner/cross_cutting_complexity_layers/corner_layers_optimistic_concurrency_corrective_action_guards_the_revision_counter
        """
        fx.set_clock(api, STARTUP_CLOCK)
        env = _retest_passed_case(api)
        case_id = env["case"]["id"]
        fx.file_corrective_action(api, case_id, env["case"]["version"], ref="CAP-2026-0041")
        validate_error(
            api.file_corrective_action(
                case_id,
                {
                    "expected_case_version": env["case"]["version"],
                    "corrective_action_ref": "CAP-2026-0042",
                },
                headers=OFFICER_HEADERS,
            ),
            ApiErrorId.STALE_CASE_VERSION.value,
            412,
        )

        fresh = fx.get_case(api, case_id)
        revised = validate_success(
            api.file_corrective_action(
                case_id,
                {
                    "expected_case_version": fresh["version"],
                    "corrective_action_ref": "CAP-2026-0042",
                },
                headers=OFFICER_HEADERS,
            ),
            200,
        )
        assert revised["corrective_action_ref"] == "CAP-2026-0042"
        assert revised["corrective_action_revision"] == 2

    def test_unrelated_case_writes_also_advance_the_guarded_version(self, api):
        """PRD 2.6: "Recording a corrective action plan on a noncompliance case requires
        `expected_case_version` as a non-optional field of the request body, carrying the
        `version` of the `NoncomplianceCase` the client last read." — stop-distribution and
        retest ordering both increment that same `version`.

        Design: Corner/cross_cutting_complexity_layers/corner_layers_optimistic_concurrency_corrective_action_guards_the_revision_counter
        """
        fx.set_clock(api, STARTUP_CLOCK)
        env = fx.failed_case_env(api, release=False)
        case_id = env["case"]["id"]
        version_at_open = env["case"]["version"]

        stopped = fx.issue_stop_distribution(api, case_id)
        assert stopped["version"] == version_at_open + 1
        ordered = fx.order_retest(api, case_id, env["plan"]["id"], env["laboratory"]["id"])
        assert ordered["version"] == stopped["version"] + 1
        retest_order_id = ordered["active_retest_order_id"]
        fx.start_order(api, retest_order_id, env["laboratory"]["id"])
        fx.report(api, retest_order_id, env["laboratory"]["id"], 10)

        validate_error(
            api.file_corrective_action(
                case_id,
                {
                    "expected_case_version": version_at_open,
                    "corrective_action_ref": "CAP-2026-0099",
                },
                headers=OFFICER_HEADERS,
            ),
            ApiErrorId.STALE_CASE_VERSION.value,
            412,
        )
        current = fx.get_case(api, case_id)
        assert current["case_state"] == "RETEST_PASSED"
        assert current["corrective_action_revision"] == 0
        filed = fx.file_corrective_action(api, case_id, current["version"], ref="CAP-2026-0099")
        assert filed["corrective_action_revision"] == 1

    def test_the_two_guards_never_share_a_code(self, api):
        """PRD 2.6: "No other operation in the system takes a version field. Endpoints outside
        these two neither require nor accept `expected_product_version` or
        `expected_case_version`." — each guard reports its own parent's code.

        Design: Corner/cross_cutting_complexity_layers/corner_layers_optimistic_concurrency_corrective_action_guards_the_revision_counter
        """
        fx.set_clock(api, STARTUP_CLOCK)
        env = _retest_passed_case(api)
        case = env["case"]
        product_id = fx.evidence_complete_env(api)["product"]["id"]

        validate_error(
            api.file_corrective_action(
                case["id"],
                {
                    "expected_case_version": case["version"] + 5,
                    "corrective_action_ref": "CAP-2026-0100",
                },
                headers=OFFICER_HEADERS,
            ),
            ApiErrorId.STALE_CASE_VERSION.value,
            412,
        )
        product_version = fx.get_product(api, product_id)["version"]
        validate_error(
            api.draft_certificate(
                product_id,
                factories.certificate_payload(product_version + 5),
                headers=OFFICER_HEADERS,
            ),
            ApiErrorId.STALE_PRODUCT_VERSION.value,
            412,
        )


class TestComputedFieldsRecomputeRatherThanAccumulate:
    """Unit buckets and scores are recomputed; fee totals and counters only ever rise."""

    def test_the_unit_buckets_move_in_opposite_directions_and_still_sum(self, api):
        """PRD 2.8: "Every production batch's `quantity` sits in exactly one of the product's four
        counters at any instant: `units_held`, `units_released`, `units_stopped` or
        `units_destroyed`. The invariant is that the sum of those four counters equals the total
        `quantity` produced across every batch of the product".

        Design: Corner/cross_cutting_complexity_layers/corner_layers_computed_fields_recompute_rather_than_accumulate
        """
        fx.set_clock(api, STARTUP_CLOCK)
        env = fx.distributed_env(api, batch_specs=[{}, {}], release=False)
        product_id = env["product"]["id"]
        batch = env["batches"][0]
        assert batch["quantity"] == 100
        held_only = fx.get_product(api, product_id)
        assert held_only["units_held"] == 200
        assert held_only["units_released"] == 0

        fx.release_batch(api, batch["id"])
        released = fx.get_product(api, product_id)
        assert released["units_held"] == 100
        assert released["units_released"] == 100

        fx.rescind_release(api, batch["id"])
        rescinded = fx.get_product(api, product_id)
        assert rescinded["units_held"] == 200
        assert rescinded["units_released"] == 0

        summary = fx.get_summary(api, product_id)
        assert summary["units_total_produced"] == 200
        assert (
            summary["units_held"]
            + summary["units_released"]
            + summary["units_stopped"]
            + summary["units_destroyed"]
            == summary["units_total_produced"]
        )
        assert summary["ledger_balanced"] is True

    def test_the_rescind_counter_records_history_the_state_no_longer_shows(self, api):
        """PRD 3.8: "Rescinding a release moves the batch `RELEASED → HELD`, moves the same
        `quantity` from the product's `units_released` back to `units_held`, clears `released_at`
        to null, increments `release_rescind_count` by 1".

        Design: Corner/cross_cutting_complexity_layers/corner_layers_computed_fields_recompute_rather_than_accumulate
        """
        fx.set_clock(api, STARTUP_CLOCK)
        env = fx.distributed_env(api, release=False)
        batch_id = env["batches"][0]["id"]
        assert env["batches"][0]["release_rescind_count"] == 0

        fx.release_batch(api, batch_id)
        first = fx.rescind_release(api, batch_id)
        assert first["distribution_state"] == "HELD"
        assert first["release_rescind_count"] == 1
        assert first["released_at"] is None

        fx.release_batch(api, batch_id)
        second = fx.rescind_release(api, batch_id)
        assert second["distribution_state"] == "HELD"
        assert second["release_rescind_count"] == 2

    def test_the_billed_fee_total_is_an_accumulator_and_the_balance_is_the_difference(self, api):
        """PRD 2.8: "The invariant is that `billed_fee_cents_total` minus
        `credited_fee_cents_total` equals that outstanding balance. Every order is billed at
        creation, and cancellation or invalidation credits back the exact `invoice_total_cents`
        that was billed".

        Design: Corner/cross_cutting_complexity_layers/corner_layers_computed_fields_recompute_rather_than_accumulate
        """
        fx.set_clock(api, STARTUP_CLOCK)
        env = fx.booking_env(api)
        laboratory_id = env["laboratory"]["id"]
        before = fx.get_laboratory(api, laboratory_id)
        assert before["billed_fee_cents_total"] == 0
        assert before["credited_fee_cents_total"] == 0

        order = fx.book_order(
            api,
            env["product"]["id"],
            env["plan"]["id"],
            laboratory_id,
            env["rules"][0]["id"],
        )
        assert order["invoice_total_cents"] == 18700
        billed = fx.get_laboratory(api, laboratory_id)
        assert billed["billed_fee_cents_total"] == 18700
        assert billed["credited_fee_cents_total"] == 0

        validate_success(api.cancel_test_order(order["id"], headers=COORDINATOR_HEADERS), 200)
        after = fx.get_laboratory(api, laboratory_id)
        assert after["billed_fee_cents_total"] == 18700
        assert after["credited_fee_cents_total"] == 18700
        assert after["billed_fee_cents_total"] - after["credited_fee_cents_total"] == 0

    def test_the_supplier_filing_count_follows_the_declared_branch_of_each_decision(self, api):
        """PRD 3.4: "the supplier's `certificates_issued_count` is left exactly as it is, because
        a relied-upon row was already inside the counted set" on `RELY`, while on `REJECT` "the
        supplier's `certificates_issued_count` is decremented by 1, because a rejected row leaves
        the counted set".

        Design: Corner/cross_cutting_complexity_layers/corner_layers_computed_fields_recompute_rather_than_accumulate
        """
        fx.set_clock(api, STARTUP_CLOCK)
        env = fx.reliance_env(api, rely=False, rule_specs=[{}, {}])
        supplier_id = env["supplier"]["id"]
        assert fx.get_supplier(api, supplier_id)["certificates_issued_count"] == 2

        fx.record_reliance(api, env["part_certificates"][0]["id"], decision="RELY")
        assert fx.get_supplier(api, supplier_id)["certificates_issued_count"] == 2

        fx.record_reliance(api, env["part_certificates"][1]["id"], decision="REJECT")
        assert fx.get_supplier(api, supplier_id)["certificates_issued_count"] == 1

    def test_the_change_count_tracks_its_rows_and_the_summary_read_is_pure(self, api):
        """PRD 3.10: "Recording the event always increments the product's `material_change_count`
        by 1, whichever way the resample decision falls." — PRD 2.8: "It is a pure read: it
        mutates no row and bumps no `version`."

        Design: Corner/cross_cutting_complexity_layers/corner_layers_computed_fields_recompute_rather_than_accumulate
        """
        fx.set_clock(api, STARTUP_CLOCK)
        env = fx.scoped_product_env(api)
        product_id = env["product"]["id"]
        assert fx.get_product(api, product_id)["material_change_count"] == 0

        fx.record_material_change(api, product_id, change_kind="PACKAGING_ONLY")
        fx.record_material_change(api, product_id, change_kind="PACKAGING_ONLY")
        _, meta = validate_paginated(
            api.list_material_changes({"product_id": product_id}, headers=ADMIN_HEADERS)
        )
        assert meta["total_count"] == 2
        assert fx.get_product(api, product_id)["material_change_count"] == 2

        version_before = fx.get_product(api, product_id)["version"]
        first_summary = fx.get_summary(api, product_id)
        second_summary = fx.get_summary(api, product_id)
        assert first_summary == second_summary
        assert fx.get_product(api, product_id)["version"] == version_before
