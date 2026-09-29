"""Error-code corners: the twelve not-found families each name their own entity
and obey two ordering rules, the entity-state conflicts name the entity whose
state actually blocked the call, the tail of the note past the power of attorney
carries six codes nothing earlier can reach, and the statutory ceiling bounds the
very exception that exists to bend it.
"""

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    commission_cap_cents,
    deficiency_fee_cents,
    factories,
    fixtures,
    late_fee_cents,
    note_settlement_residual_cents,
    pro_rata_unearned_premium_cents,
    round_half_up,
    rule_of_78_rebate_cents,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.test_users import (
    ANALYST_EXECUTOR,
    ANALYST_NOTICE,
    ANALYST_ORIGIN,
    COMPLIANCE,
    COMPLIANCE_APPROVER,
    make_compliance_headers,
)

COLLECTIONS = make_compliance_headers("compliance-collections")


class TestNotFoundFamilyNamesTheExactDanglingReference:
    """Every path family answers with the code for its own entity, and both the
    path order and the declared body order decide which one is reported."""

    def _real_rows(self, api):
        """One real regime with a licence, one borrower, one agency, one carrier.

        Every probe below then addresses a well-formed identifier that matches no
        row at all, so the only thing under test is which code comes back.
        """
        fixtures.set_clock(api, "2026-08-15T00:00:00Z")
        ctx = fixtures.create_state_regime(
            api,
            rule_payload=factories.tx_state_rate_rule(),
            license_payload=factories.license_payload(license_number="PFC-TX-001"),
        )
        ctx.update(fixtures.create_parties(api))
        return ctx

    def test_the_regime_and_licence_families_each_name_themselves(self, api):
        """A ghost regime reports the regime; a ghost licence reports the licence.

        The PRD states: "A request naming a state rate regime that does not exist
        fails with `ERR_STATE_RULE_NOT_FOUND`; an unknown `license_id` yields
        `ERR_LICENSE_NOT_FOUND`".

        Design: Corner/errors/error_triggerable_not_found_family_names_the_exact_dangling_reference
        """
        self._real_rows(api)

        validate_error(
            api.get_state_rate_rule(NON_EXISTENT_UUID, COMPLIANCE),
            ApiErrorId.STATE_RULE_NOT_FOUND.value,
            404,
        )
        validate_error(
            api.suspend_license(NON_EXISTENT_UUID, COMPLIANCE),
            ApiErrorId.LICENSE_NOT_FOUND.value,
            404,
        )

    def test_the_party_and_note_families_each_name_themselves(self, api):
        """A ghost agency, a ghost note and a ghost policy report three codes.

        The PRD states: "an unknown `agent_id` yields `ERR_AGENT_NOT_FOUND`; an
        unknown `agreement_id` yields `ERR_AGREEMENT_NOT_FOUND`; an unknown
        `policy_id` yields `ERR_POLICY_NOT_FOUND`".

        Design: Corner/errors/error_triggerable_not_found_family_names_the_exact_dangling_reference
        """
        self._real_rows(api)

        validate_error(
            api.get_agent(NON_EXISTENT_UUID, COMPLIANCE),
            ApiErrorId.AGENT_NOT_FOUND.value,
            404,
        )
        validate_error(
            api.submit_agreement(NON_EXISTENT_UUID, ANALYST_ORIGIN),
            ApiErrorId.AGREEMENT_NOT_FOUND.value,
            404,
        )
        validate_error(
            api.get_policy(NON_EXISTENT_UUID, ANALYST_ORIGIN),
            ApiErrorId.POLICY_NOT_FOUND.value,
            404,
        )

    def test_the_ledger_row_families_each_name_themselves(self, api):
        """A ghost payment and a ghost late fee report their own codes.

        The PRD states: "an unknown `payment_id` yields `ERR_PAYMENT_NOT_FOUND`;
        an unknown `late_fee_id` yields `ERR_LATE_FEE_NOT_FOUND`".

        Design: Corner/errors/error_triggerable_not_found_family_names_the_exact_dangling_reference
        """
        self._real_rows(api)

        validate_error(
            api.reverse_payment(NON_EXISTENT_UUID, factories.reversal(), ANALYST_ORIGIN),
            ApiErrorId.PAYMENT_NOT_FOUND.value,
            404,
        )
        validate_error(
            api.waive_late_fee(NON_EXISTENT_UUID, factories.waiver(), COMPLIANCE),
            ApiErrorId.LATE_FEE_NOT_FOUND.value,
            404,
        )

    def test_the_collection_families_each_name_themselves(self, api):
        """A ghost cancellation request, endorsement and chargeback report three
        distinct codes rather than one generic miss.

        The PRD states: "an unknown `request_id` yields
        `ERR_CANCEL_REQUEST_NOT_FOUND`; an unknown `endorsement_id` yields
        `ERR_ENDORSEMENT_NOT_FOUND`; and an unknown `chargeback_id` yields
        `ERR_CHARGEBACK_NOT_FOUND`".

        Design: Corner/errors/error_triggerable_not_found_family_names_the_exact_dangling_reference
        """
        self._real_rows(api)

        validate_error(
            api.get_carrier_cancellation_request(NON_EXISTENT_UUID, COMPLIANCE),
            ApiErrorId.CANCEL_REQUEST_NOT_FOUND.value,
            404,
        )
        validate_error(
            api.decline_endorsement(
                NON_EXISTENT_UUID, ANALYST_ORIGIN, factories.decline_reason()
            ),
            ApiErrorId.ENDORSEMENT_NOT_FOUND.value,
            404,
        )
        validate_error(
            api.get_agent_chargeback(NON_EXISTENT_UUID, COMPLIANCE),
            ApiErrorId.CHARGEBACK_NOT_FOUND.value,
            404,
        )

    def test_every_family_answers_at_http_404(self, api):
        """The whole family shares one status code and differs only in the id.

        The PRD states: "Every one of these is an HTTP 404."

        Design: Corner/errors/error_triggerable_not_found_family_names_the_exact_dangling_reference
        """
        self._real_rows(api)

        probes = [
            (api.get_state_rate_rule(NON_EXISTENT_UUID, COMPLIANCE),
             ApiErrorId.STATE_RULE_NOT_FOUND.value),
            (api.suspend_license(NON_EXISTENT_UUID, COMPLIANCE),
             ApiErrorId.LICENSE_NOT_FOUND.value),
            (api.get_agent(NON_EXISTENT_UUID, COMPLIANCE),
             ApiErrorId.AGENT_NOT_FOUND.value),
            (api.submit_agreement(NON_EXISTENT_UUID, ANALYST_ORIGIN),
             ApiErrorId.AGREEMENT_NOT_FOUND.value),
            (api.get_policy(NON_EXISTENT_UUID, ANALYST_ORIGIN),
             ApiErrorId.POLICY_NOT_FOUND.value),
            (api.get_carrier_cancellation_request(NON_EXISTENT_UUID, COMPLIANCE),
             ApiErrorId.CANCEL_REQUEST_NOT_FOUND.value),
            (api.get_agent_chargeback(NON_EXISTENT_UUID, COMPLIANCE),
             ApiErrorId.CHARGEBACK_NOT_FOUND.value),
        ]
        seen = set()
        for response, error_id in probes:
            body = validate_error(response, error_id, 404)
            seen.add(body["error_id"])
        assert len(seen) == len(probes), (
            "each family reports a code of its own, so seven probes produce seven "
            "distinct error ids"
        )

    def test_the_leftmost_missing_path_segment_decides(self, api):
        """A licence written under a ghost regime reports the regime.

        The PRD states: "Because resolution is left to right, a licence read under
        a non-existent state regime reports the state regime as missing rather than
        the licence."

        Design: Corner/errors/error_triggerable_not_found_family_names_the_exact_dangling_reference
        """
        self._real_rows(api)

        validate_error(
            api.create_license(
                NON_EXISTENT_UUID,
                factories.license_payload(license_number="PFC-TX-999"),
                COMPLIANCE,
            ),
            ApiErrorId.STATE_RULE_NOT_FOUND.value,
            404,
        )
        validate_error(
            api.list_licenses(NON_EXISTENT_UUID, COMPLIANCE, {"limit": 50}),
            ApiErrorId.STATE_RULE_NOT_FOUND.value,
            404,
        )

    def test_all_three_bogus_body_keys_report_the_borrower(self, api):
        """With every foreign key dangling, the first declared one is reported.

        The PRD states: "Foreign keys supplied in a request body are resolved in
        the order in which they are declared for that operation, which for
        agreement creation and policy attachment means `insured_id`, then
        `producer_agent_id`, then `state_rule_id`, then `insurer_id`."

        Design: Corner/errors/error_triggerable_not_found_family_names_the_exact_dangling_reference
        """
        self._real_rows(api)

        validate_error(
            api.create_agreement(
                factories.agreement(
                    NON_EXISTENT_UUID, NON_EXISTENT_UUID, NON_EXISTENT_UUID
                ),
                ANALYST_ORIGIN,
            ),
            ApiErrorId.INSURED_NOT_FOUND.value,
            404,
        )

    def test_repairing_the_references_one_at_a_time_walks_three_codes(self, api):
        """The same request reports the borrower, then the agency, then the regime.

        The PRD states: "An unresolvable borrower yields `ERR_INSURED_NOT_FOUND`,
        an unresolvable agency `ERR_AGENT_NOT_FOUND`, an unresolvable state regime
        `ERR_STATE_RULE_NOT_FOUND` and an unresolvable carrier
        `ERR_INSURER_NOT_FOUND`, all HTTP 404."

        Design: Corner/errors/error_triggerable_not_found_family_names_the_exact_dangling_reference
        """
        ctx = self._real_rows(api)

        validate_error(
            api.create_agreement(
                factories.agreement(
                    NON_EXISTENT_UUID, NON_EXISTENT_UUID, NON_EXISTENT_UUID
                ),
                ANALYST_ORIGIN,
            ),
            ApiErrorId.INSURED_NOT_FOUND.value,
            404,
        )
        validate_error(
            api.create_agreement(
                factories.agreement(
                    ctx["insured_id"], NON_EXISTENT_UUID, NON_EXISTENT_UUID
                ),
                ANALYST_ORIGIN,
            ),
            ApiErrorId.AGENT_NOT_FOUND.value,
            404,
        )
        validate_error(
            api.create_agreement(
                factories.agreement(
                    ctx["insured_id"], ctx["agent_id"], NON_EXISTENT_UUID
                ),
                ANALYST_ORIGIN,
            ),
            ApiErrorId.STATE_RULE_NOT_FOUND.value,
            404,
        )

    def test_an_unresolvable_carrier_is_reported_after_the_path_parent(self, api):
        """The path note resolves first, then the body carrier fails to.

        The PRD states: "4. Every foreign key in the body resolves, in declared
        order — otherwise the corresponding not-found code."

        Design: Corner/errors/error_triggerable_not_found_family_names_the_exact_dangling_reference
        """
        ctx = self._real_rows(api)
        agreement = validate_success(
            api.create_agreement(
                factories.agreement(
                    ctx["insured_id"], ctx["agent_id"], ctx["rule_id"]
                ),
                ANALYST_ORIGIN,
            ),
            201,
        )

        validate_error(
            api.attach_policy(
                agreement["id"],
                factories.financed_policy(
                    NON_EXISTENT_UUID, policy_number="MC-NF-1"
                ),
                ANALYST_ORIGIN,
            ),
            ApiErrorId.INSURER_NOT_FOUND.value,
            404,
        )
        validate_error(
            api.attach_policy(
                NON_EXISTENT_UUID,
                factories.financed_policy(
                    NON_EXISTENT_UUID, policy_number="MC-NF-2"
                ),
                ANALYST_ORIGIN,
            ),
            ApiErrorId.AGREEMENT_NOT_FOUND.value,
            404,
        )

    def test_none_of_the_probes_wrote_anything(self, api):
        """The one legitimately created note is untouched by every refusal.

        The PRD states: "`version` starts at 1 when the row is created and
        increases by exactly 1 on every mutation of that row; `updated_at` is
        refreshed to the logical-clock instant on the same mutation."

        Design: Corner/errors/error_triggerable_not_found_family_names_the_exact_dangling_reference
        """
        ctx = self._real_rows(api)
        agreement = validate_success(
            api.create_agreement(
                factories.agreement(
                    ctx["insured_id"], ctx["agent_id"], ctx["rule_id"]
                ),
                ANALYST_ORIGIN,
            ),
            201,
        )

        validate_error(
            api.attach_policy(
                agreement["id"],
                factories.financed_policy(
                    NON_EXISTENT_UUID, policy_number="MC-NF-3"
                ),
                ANALYST_ORIGIN,
            ),
            ApiErrorId.INSURER_NOT_FOUND.value,
            404,
        )
        validate_error(
            api.submit_agreement(NON_EXISTENT_UUID, ANALYST_ORIGIN),
            ApiErrorId.AGREEMENT_NOT_FOUND.value,
            404,
        )

        read_back = fixtures.read_agreement(api, agreement["id"])
        assert read_back["policy_count"] == 0, (
            "the attachment that named a dangling carrier attached nothing"
        )
        assert read_back["version"] == 1, (
            "a refused request is not a mutation, so the note is still on the "
            "version it was created with"
        )


class TestEntityStateConflictsReportTheAddressedEntity:
    """Each 409 names the entity whose own state blocked the call, and the
    precedence between two applicable conflicts is itself fixed."""

    def _two_policies(self, api):
        """A submitted note carrying one settled policy and one still open.

        The first policy has both attestations and is therefore `VERIFIED`; the
        second carries only the carrier's voice and stays open. One endorsement is
        filed on the settled policy, which is the second dead end this scenario
        needs.
        """
        ctx = fixtures.origination_context(
            api,
            insured_payload=factories.insured(
                legal_name="Cascade Logistics Inc", email="ap@cascade.example"
            ),
        )
        bundle = fixtures.draft_agreement(
            api,
            ctx,
            policies=[
                factories.financed_policy(
                    ctx["insurer_id"],
                    policy_number="MC-SC-1",
                    gross_premium_cents=600000,
                ),
                factories.financed_policy(
                    ctx["insurer_id"],
                    policy_number="MC-SC-2",
                    gross_premium_cents=400000,
                ),
            ],
            down_payment_cents=200000,
        )
        bundle["submitted"] = validate_success(
            api.submit_agreement(bundle["agreement_id"], ANALYST_ORIGIN), 200
        )
        bundle["p1"], bundle["p2"] = bundle["policy_ids"]
        validate_success(
            api.create_verification(
                bundle["p1"], factories.confirmed_verification(), bundle["insurer_headers"]
            ),
            201,
        )
        validate_success(
            api.create_verification(
                bundle["p1"], factories.confirmed_verification(), bundle["agent_headers"]
            ),
            201,
        )
        validate_success(
            api.create_verification(
                bundle["p2"], factories.confirmed_verification(), bundle["insurer_headers"]
            ),
            201,
        )
        bundle["endorsement"] = validate_success(
            api.create_endorsement(
                bundle["p1"],
                factories.endorsement(60000, effective_date="2026-09-15"),
                bundle["agent_headers"],
            ),
            201,
        )
        return bundle

    def test_the_two_policies_settle_in_different_states(self, api):
        """Two concurring voices close a policy; one voice does not.

        The PRD states: "Nothing happens to the policy while only one side has
        spoken; the policy stays `PENDING_VERIFICATION` until both parties hold a
        non-superseded record."

        Design: Corner/errors/error_triggerable_entity_state_conflicts_report_the_addressed_entity
        """
        bundle = self._two_policies(api)

        assert fixtures.read_policy(api, bundle["p1"])["status"] == "VERIFIED"
        assert (
            fixtures.read_policy(api, bundle["p2"])["status"] == "PENDING_VERIFICATION"
        )
        assert fixtures.read_agreement(api, bundle["agreement_id"])[
            "verified_policy_count"
        ] == 1

    def test_the_policys_state_outranks_the_duplicate_attestation_check(self, api):
        """A repeat carrier voice on a settled policy reports the policy's state.

        The PRD states: "The policy itself must be `PENDING_VERIFICATION`; a
        `VERIFIED`, `DISPUTED` or `CANCELLED` policy refuses the filing with
        `ERR_POLICY_STATE_INVALID` (HTTP 409)."

        Design: Corner/errors/error_triggerable_entity_state_conflicts_report_the_addressed_entity
        """
        bundle = self._two_policies(api)

        validate_error(
            api.create_verification(
                bundle["p1"],
                factories.confirmed_verification(),
                bundle["insurer_headers"],
            ),
            ApiErrorId.POLICY_STATE_INVALID.value,
            409,
        )

    def test_the_same_repeat_on_an_open_policy_reports_the_duplicate(self, api):
        """On a policy still open, the carrier's second voice is the duplicate.

        The PRD states: "Each side gets one live voice per policy: if a
        non-superseded attestation from the same party already exists on that
        policy, the filing is refused with `ERR_VERIFICATION_ALREADY_RECORDED`
        (HTTP 409)."

        Design: Corner/errors/error_triggerable_entity_state_conflicts_report_the_addressed_entity
        """
        bundle = self._two_policies(api)

        validate_error(
            api.create_verification(
                bundle["p2"],
                factories.confirmed_verification(),
                bundle["insurer_headers"],
            ),
            ApiErrorId.VERIFICATION_ALREADY_RECORDED.value,
            409,
        )

    def test_reopening_a_settled_policy_reports_the_policys_own_state(self, api):
        """Reopening demands a disputed policy, and a settled one is not that.

        The PRD states: "13. The policy's `status` permits the operation —
        otherwise `ERR_POLICY_STATE_INVALID`. Filing an attestation requires
        `PENDING_VERIFICATION`, reopening requires `DISPUTED`, and filing an
        endorsement requires `PENDING_VERIFICATION` or `VERIFIED`."

        Design: Corner/errors/error_triggerable_entity_state_conflicts_report_the_addressed_entity
        """
        bundle = self._two_policies(api)

        validate_error(
            api.reopen_verification(bundle["p1"], ANALYST_ORIGIN),
            ApiErrorId.POLICY_STATE_INVALID.value,
            409,
        )
        validate_error(
            api.reopen_verification(bundle["p2"], ANALYST_ORIGIN),
            ApiErrorId.POLICY_STATE_INVALID.value,
            409,
        )

    def test_the_second_decline_reports_the_endorsement_and_not_its_parents(self, api):
        """The first decline lands; the second names the endorsement's own state.

        The PRD states: "declining a `PENDING` endorsement moves it `PENDING` →
        `DECLINED`, optionally recording a `reason`, and advances its `version`; an
        endorsement that is not `PENDING` refuses the decline with
        `ERR_ENDORSEMENT_STATE_INVALID`."

        Design: Corner/errors/error_triggerable_entity_state_conflicts_report_the_addressed_entity
        """
        bundle = self._two_policies(api)

        declined = validate_success(
            api.decline_endorsement(
                bundle["endorsement"]["id"],
                ANALYST_ORIGIN,
                factories.decline_reason(reason="carrier withdrew the amendment"),
            ),
            200,
        )
        assert declined["status"] == "DECLINED"

        validate_error(
            api.decline_endorsement(
                bundle["endorsement"]["id"],
                ANALYST_ORIGIN,
                factories.decline_reason(reason="declining a second time"),
            ),
            ApiErrorId.ENDORSEMENT_STATE_INVALID.value,
            409,
        )

    def test_the_refusals_wrote_no_duplicate_rows(self, api):
        """Every refused filing left the attestation and endorsement lists alone.

        The PRD states: "A `PremiumVerification` — the attestation a carrier or an
        agency files against a policy — is an immutable audit record: it carries
        only `id` and `created_at`."

        Design: Corner/errors/error_triggerable_entity_state_conflicts_report_the_addressed_entity
        """
        bundle = self._two_policies(api)
        validate_error(
            api.create_verification(
                bundle["p1"],
                factories.confirmed_verification(),
                bundle["insurer_headers"],
            ),
            ApiErrorId.POLICY_STATE_INVALID.value,
            409,
        )
        validate_error(
            api.create_verification(
                bundle["p2"],
                factories.confirmed_verification(),
                bundle["insurer_headers"],
            ),
            ApiErrorId.VERIFICATION_ALREADY_RECORDED.value,
            409,
        )
        validate_success(
            api.decline_endorsement(
                bundle["endorsement"]["id"],
                ANALYST_ORIGIN,
                factories.decline_reason(reason="carrier withdrew the amendment"),
            ),
            200,
        )
        validate_error(
            api.decline_endorsement(
                bundle["endorsement"]["id"],
                ANALYST_ORIGIN,
                factories.decline_reason(reason="declining a second time"),
            ),
            ApiErrorId.ENDORSEMENT_STATE_INVALID.value,
            409,
        )

        _, p1_meta = validate_paginated(
            api.list_verifications(bundle["p1"], ANALYST_ORIGIN, {"limit": 50})
        )
        assert p1_meta["total_count"] == 2
        _, p2_meta = validate_paginated(
            api.list_verifications(bundle["p2"], ANALYST_ORIGIN, {"limit": 50})
        )
        assert p2_meta["total_count"] == 1
        rows, meta = validate_paginated(
            api.list_endorsements(
                bundle["p1"], ANALYST_ORIGIN, {"status": "DECLINED", "limit": 50}
            )
        )
        assert meta["total_count"] == 1
        assert rows[0]["id"] == bundle["endorsement"]["id"]

    def test_the_note_stayed_where_it_was(self, api):
        """Six refusals on children moved neither dimension of the parent note.

        The PRD states: "Submitting the draft advances the financing status `DRAFT`
        → `PENDING_VERIFICATION` and prices the note provisionally."

        Design: Corner/errors/error_triggerable_entity_state_conflicts_report_the_addressed_entity
        """
        bundle = self._two_policies(api)
        before = fixtures.read_agreement(api, bundle["agreement_id"])

        for probe, expected in [
            (
                api.create_verification(
                    bundle["p1"],
                    factories.confirmed_verification(),
                    bundle["insurer_headers"],
                ),
                ApiErrorId.POLICY_STATE_INVALID.value,
            ),
            (
                api.create_verification(
                    bundle["p2"],
                    factories.confirmed_verification(),
                    bundle["insurer_headers"],
                ),
                ApiErrorId.VERIFICATION_ALREADY_RECORDED.value,
            ),
            (
                api.reopen_verification(bundle["p1"], ANALYST_ORIGIN),
                ApiErrorId.POLICY_STATE_INVALID.value,
            ),
            (
                api.reopen_verification(bundle["p2"], ANALYST_ORIGIN),
                ApiErrorId.POLICY_STATE_INVALID.value,
            ),
        ]:
            validate_error(probe, expected, 409)

        after = fixtures.read_agreement(api, bundle["agreement_id"])
        assert before["status"] == "PENDING_VERIFICATION"
        assert after["status"] == "PENDING_VERIFICATION"
        assert after["version"] == before["version"]
        assert after["verified_policy_count"] == 1


class TestPowerOfAttorneyAndDeficiencyCollectionErrorWalk:
    """The tail of the note carries codes that only become reachable once the
    previous step of the cascade has actually succeeded."""

    def _noticed(self, api):
        """The 600k note delinquent at 2026-10-12 under one ISSUED notice."""
        bundle = fixtures.noticed_note(api, policy_number="MC-DW-1")
        return bundle

    def _cancelled(self, api):
        """The same note with the power of attorney exercised on 2026-10-22.

        The notice was issued under one analyst handle and the execution runs under
        another, because the two may never be the same person.
        """
        bundle = self._noticed(api)
        return fixtures.cancelled_note(
            api,
            bundle=bundle,
            execute_at="2026-10-22T00:00:00Z",
            executor_headers=ANALYST_EXECUTOR,
        )

    def _settled(self, api):
        """The cancelled note settled by a single short carrier return."""
        bundle = self._cancelled(api)
        fixtures.set_clock(api, "2026-10-25T00:00:00Z")
        return fixtures.settled_note(
            api,
            bundle=bundle,
            carrier_returned_cents=300000,
            posted_date="2026-10-25",
        )

    def test_the_walk_starts_from_the_expected_priced_and_noticed_state(self, api):
        """One fee, a ten-day notice and a frozen statement of the arrears.

        The PRD states: "It also snapshots `past_due_amount_cents`: the sum, over
        the note's installments whose `status` is `PAST_DUE`, of each installment's
        `amount_cents` minus its `paid_cents`, plus the note's
        `late_fee_balance_cents`."

        Design: Corner/errors/error_triggerable_power_of_attorney_and_deficiency_collection_error_walk
        """
        bundle = self._noticed(api)

        assert bundle["activated"]["total_premium_cents"] == 600000
        assert bundle["activated"]["finance_charge_cents"] == 37650
        assert bundle["activated"]["total_of_payments_cents"] == 539650
        assert len(bundle["late_fees"]) == 1
        assert bundle["late_fee_amount_cents"] == late_fee_cents(89941, 500, 500, 10000)
        assert bundle["late_fee_amount_cents"] == 4497

        notice = bundle["notice"]
        assert notice["status"] == "ISSUED"
        assert notice["notice_days"] == 10
        assert notice["issued_date"] == "2026-10-12"
        assert notice["effective_cancel_date"] == "2026-10-22"
        assert notice["past_due_amount_cents"] == 89941 + 4497 == 94438

    def test_an_occupied_notice_window_reports_itself(self, api):
        """A second notice while the first is open names the window, not the stage.

        The PRD states: "A note may carry only one open notice at a time: if any
        notice of the note is already `ISSUED`, the request is refused with
        `ERR_NOTICE_WINDOW_OPEN` (HTTP 409) — that occupied window is also why a
        note already in `NOIC_ISSUED` clears the stage gate and is refused here
        instead, so the caller learns the real reason."

        Design: Corner/errors/error_triggerable_power_of_attorney_and_deficiency_collection_error_walk
        """
        bundle = self._noticed(api)

        validate_error(
            api.issue_cancellation_notice(bundle["agreement_id"], ANALYST_NOTICE),
            ApiErrorId.NOTICE_WINDOW_OPEN.value,
            409,
        )

        rows, meta = validate_paginated(
            api.list_cancellation_notices(
                bundle["agreement_id"], ANALYST_NOTICE, {"limit": 50}
            )
        )
        assert meta["total_count"] == 1, "the refusal wrote no second notice row"
        assert rows[0]["id"] == bundle["notice_id"]
        assert rows[0]["status"] == "ISSUED"
        assert rows[0]["past_due_amount_cents"] == 94438, (
            "the frozen statement was not re-snapshotted"
        )
        assert rows[0]["effective_cancel_date"] == "2026-10-22", (
            "and the statutory clock was not restarted"
        )

    def test_execution_before_the_effective_date_is_refused(self, api):
        """The statutory notice must run in full before the power is exercised.

        The PRD states: "the clock date must be on or after that notice's
        `effective_cancel_date`, or the attempt is refused with
        `ERR_NOTICE_PERIOD_NOT_ELAPSED` (HTTP 422), with the boundary day itself
        permitted".

        Design: Corner/errors/error_triggerable_power_of_attorney_and_deficiency_collection_error_walk
        """
        bundle = self._noticed(api)

        validate_error(
            api.execute_cancellation(bundle["agreement_id"], ANALYST_EXECUTOR),
            ApiErrorId.NOTICE_PERIOD_NOT_ELAPSED.value,
            422,
        )

        agreement = fixtures.read_agreement(api, bundle["agreement_id"])
        assert agreement["delinquency_stage"] == "NOIC_ISSUED", (
            "the refused execution left the collection dimension where it was"
        )

    def test_execution_on_the_boundary_day_reports_the_whole_cancellation(self, api):
        """On the effective cancel date the same call succeeds and quantifies itself.

        The PRD states: "The operation reports `requests_created`, the aggregate
        `estimated_unearned_premium_cents`, the `rebate_applied_cents` it granted,
        and the `gross_balance_cents` of the note — its `principal_balance_cents`
        plus its post-rebate `unpaid_finance_charge_cents`."

        Design: Corner/errors/error_triggerable_power_of_attorney_and_deficiency_collection_error_walk
        """
        bundle = self._cancelled(api)
        execution = bundle["execution"]

        assert execution["requests_created"] == 1
        assert execution["rebate_applied_cents"] == rule_of_78_rebate_cents(
            37650, 6, 6
        ) == 37650, (
            "no installment had been retired, so the whole finance charge is unearned"
        )
        assert execution["gross_balance_cents"] == 502000, (
            "principal plus the POST-rebate finance charge: the whole 37650 was "
            "just rebated, so the finance charge term is zero and the 4497 late "
            "fee is not part of this figure"
        )
        assert execution["estimated_unearned_premium_cents"] == 516164

    def test_the_estimate_is_pro_rata_over_the_half_open_term(self, api):
        """365 days of term, 51 earned, 314 unearned, rounded half up.

        The PRD states: "Otherwise the pro-rata figure is the policy's
        `financed_premium_cents` multiplied by the unearned days, divided by the
        term length in days, rounded half up."

        Design: Corner/errors/error_triggerable_power_of_attorney_and_deficiency_collection_error_walk
        """
        bundle = self._cancelled(api)

        policy = fixtures.read_policy(api, bundle["policy_id"])
        assert policy["status"] == "CANCELLED"
        assert policy["cancellation_effective_date"] == "2026-10-22"
        assert policy["earned_days"] == 51, (
            "2026-09-01 to 2026-10-22 is 51 days, above the carrier's zero floor "
            "and below the 365-day term"
        )
        assert policy["unearned_premium_estimate_cents"] == pro_rata_unearned_premium_cents(
            600000, 365 - 51, 365
        ) == 516164
        assert round_half_up(600000 * 314, 365) == 516164

    def test_an_active_note_past_cancellation_is_no_longer_restructurable(self, api):
        """The note is still ACTIVE, so the refusal is the eligibility rule.

        The PRD states: "a note whose stage is `CANCELLATION_REQUESTED` or
        `CANCELLED` is past saving, and any of these eligibility failures is
        reported as `ERR_RESTRUCTURE_NOT_ELIGIBLE` (HTTP 422)."

        Design: Corner/errors/error_triggerable_power_of_attorney_and_deficiency_collection_error_walk
        """
        bundle = self._cancelled(api)
        agreement = fixtures.read_agreement(api, bundle["agreement_id"])
        assert agreement["status"] == "ACTIVE"
        assert agreement["delinquency_stage"] == "CANCELLATION_REQUESTED"

        validate_error(
            api.restructure_agreement(
                bundle["agreement_id"],
                factories.restructure(
                    6, "2026-12-01", additional_down_payment_cents=50000
                ),
                ANALYST_ORIGIN,
            ),
            ApiErrorId.RESTRUCTURE_NOT_ELIGIBLE.value,
            422,
        )

    def test_the_request_and_the_schedule_record_the_cancellation(self, api):
        """One REQUESTED row carrying the estimate, and a voided unpaid tail.

        The PRD states: "Every installment still `SCHEDULED` with a `paid_cents` of
        zero moves to `VOIDED`, while `PAST_DUE` installments stay past due and are
        settled at the balance level rather than the schedule level."

        Design: Corner/errors/error_triggerable_power_of_attorney_and_deficiency_collection_error_walk
        """
        bundle = self._cancelled(api)

        request = validate_success(
            api.get_carrier_cancellation_request(
                bundle["cancel_request_id"], COMPLIANCE
            ),
            200,
        )
        assert request["status"] == "REQUESTED"
        assert request["computed_unearned_premium_cents"] == 516164
        assert request["estimate_method"] == "PRO_RATA"
        assert request["cancellation_effective_date"] == "2026-10-22"

        _, voided = validate_paginated(
            api.list_installments(
                bundle["agreement_id"],
                ANALYST_ORIGIN,
                {"status": "VOIDED", "limit": 100},
            )
        )
        assert voided["total_count"] == 5
        rows = fixtures.read_installments(api, bundle["agreement_id"])
        first = [row for row in rows if row["installment_number"] == 1][0]
        assert first["status"] == "PAST_DUE"

    def test_the_short_return_posts_its_shortfall(self, api):
        """A carrier paying less than the estimate stamps a negative variance.

        The PRD states: "A strictly positive return moves the request `REQUESTED` →
        `RETURN_POSTED`: `variance_cents` is stamped as `carrier_returned_cents`
        minus `computed_unearned_premium_cents`, which is negative whenever the
        carrier returned less than the platform estimated".

        Design: Corner/errors/error_triggerable_power_of_attorney_and_deficiency_collection_error_walk
        """
        bundle = self._settled(api)

        posting = bundle["return_posting"]
        assert posting["status"] == "RETURN_POSTED"
        assert posting["carrier_returned_cents"] == 300000
        assert posting["variance_cents"] == 300000 - 516164 == -216164

    def test_reporting_the_return_twice_is_refused(self, api):
        """The request has left REQUESTED, so a second cheque credits nothing.

        The PRD states: "The request must be in `REQUESTED` status, or the posting
        is refused with `ERR_CANCEL_REQUEST_STATE_INVALID` (HTTP 409)".

        Design: Corner/errors/error_triggerable_power_of_attorney_and_deficiency_collection_error_walk
        """
        bundle = self._settled(api)

        validate_error(
            api.post_carrier_return(
                bundle["cancel_request_id"],
                factories.return_posting(100000, "2026-10-25"),
                bundle["insurer_headers"],
            ),
            ApiErrorId.CANCEL_REQUEST_STATE_INVALID.value,
            409,
        )

        policy = fixtures.read_policy(api, bundle["policy_id"])
        assert policy["unearned_premium_returned_cents"] == 300000, (
            "the second attempt added nothing to the returned amount"
        )

    def test_the_credit_ran_in_the_pinned_order(self, api):
        """Principal first, and the fee is not touched by a short return.

        The PRD states: "the credit is applied to the note in a pinned order —
        first reducing `principal_balance_cents`, then
        `unpaid_finance_charge_cents`, then `late_fee_balance_cents`, with anything
        left over increasing `unapplied_credit_cents`."

        Design: Corner/errors/error_triggerable_power_of_attorney_and_deficiency_collection_error_walk
        """
        bundle = self._settled(api)

        agreement = fixtures.read_agreement(api, bundle["agreement_id"])
        assert agreement["principal_balance_cents"] == 502000 - 300000 == 202000
        assert agreement["unpaid_finance_charge_cents"] == 0, (
            "the rebate had already taken the finance charge to zero"
        )
        assert agreement["late_fee_balance_cents"] == 4497
        assert agreement["unapplied_credit_cents"] == 0
        assert agreement["unearned_premium_received_cents"] == 300000

    def test_the_deficiency_and_its_fee_close_the_note(self, api):
        """The residual before the fee keys the fee, and the sum is the deficiency.

        The PRD states: "When the residual is strictly positive, the financing
        status moves `ACTIVE` → `CANCELLED_DEFICIENT` and
        `deficiency_balance_cents` is set to the residual plus the cancellation
        fee."

        Design: Corner/errors/error_triggerable_power_of_attorney_and_deficiency_collection_error_walk
        """
        bundle = self._settled(api)

        agreement = fixtures.read_agreement(api, bundle["agreement_id"])
        residual_before_fee = 202000 + 0 + 4497 - 0
        assert residual_before_fee == 206497
        assert deficiency_fee_cents(residual_before_fee) == 5000
        assert agreement["deficiency_balance_cents"] == 206497 + 5000 == 211497
        assert agreement["status"] == "CANCELLED_DEFICIENT"
        assert agreement["delinquency_stage"] == "CANCELLED"
        assert agreement["refund_due_cents"] == 0

    def test_the_chargeback_is_commission_capped(self, api):
        """The agency answers for its commission and no more.

        The PRD states: "Under `COMMISSION_CAPPED`, the commission the agency
        earned is the note's `total_premium_cents` multiplied by the agency's
        `agent_commission_bps`, divided by 10000 and rounded half up, and
        `agent_chargeback_cents` is the smaller of `deficiency_balance_cents` and
        that commission".

        Design: Corner/errors/error_triggerable_power_of_attorney_and_deficiency_collection_error_walk
        """
        bundle = self._settled(api)

        assert commission_cap_cents(600000, 1200) == 72000
        agreement = fixtures.read_agreement(api, bundle["agreement_id"])
        assert agreement["agent_chargeback_cents"] == min(211497, 72000) == 72000

        assert len(bundle["chargebacks"]) == 1
        chargeback = bundle["chargebacks"][0]
        assert chargeback["amount_cents"] == 72000
        assert chargeback["basis"] == "COMMISSION_CAPPED"
        assert chargeback["status"] == "PENDING"
        assert chargeback["offset_applied_cents"] == 0
        assert chargeback["reason"] == "CANCELLATION_DEFICIENCY"

    def test_the_settlement_residual_is_exactly_zero(self, api):
        """Every cent is paid, rebated, returned or still owed.

        The PRD states: "Either way the collection dimension advances
        `CANCELLATION_REQUESTED` → `CANCELLED`, the note's `version` advances, and
        the note-settlement-residual identity of section 2.11 must be exactly zero
        afterwards."

        Design: Corner/errors/error_triggerable_power_of_attorney_and_deficiency_collection_error_walk
        """
        self._settled(api)

        assert note_settlement_residual_cents(
            total_of_payments_cents=539650,
            assessed_late_fees_cents=4497,
            posted_payments_cents=0,
            rebate_granted_cents=37650,
            unearned_premium_received_cents=300000,
            deficiency_before_fee_cents=206497,
            unapplied_credit_cents=0,
        ) == 0

    def test_an_offset_over_the_reserve_is_refused(self, api):
        """One cent past the agency's reserve is refused outright.

        The PRD states: "The amount must be strictly positive, must not exceed the
        chargeback's unsettled remainder (`amount_cents` minus
        `offset_applied_cents`), and must not exceed the agency's
        `chargeback_reserve_balance_cents`; a violation of either ceiling is refused
        with `ERR_OFFSET_EXCEEDS_RESERVE` (HTTP 422)."

        Design: Corner/errors/error_triggerable_power_of_attorney_and_deficiency_collection_error_walk
        """
        bundle = self._settled(api)
        chargeback = bundle["chargebacks"][0]
        agent = validate_success(api.get_agent(bundle["agent_id"], COMPLIANCE), 200)
        assert agent["chargeback_reserve_balance_cents"] == 100000

        validate_error(
            api.offset_chargeback(
                chargeback["id"],
                factories.chargeback_offset(100001, chargeback["version"]),
                COLLECTIONS,
            ),
            ApiErrorId.OFFSET_EXCEEDS_RESERVE.value,
            422,
        )

    def test_an_offset_over_the_remainder_reports_the_same_code(self, api):
        """80000 the reserve could fund still exceeds the unsettled 72000.

        The PRD states: "40. An offset fits within the agency's reserve and the
        chargeback's unsettled remainder — otherwise `ERR_OFFSET_EXCEEDS_RESERVE`,
        on a chargeback offset."

        Design: Corner/errors/error_triggerable_power_of_attorney_and_deficiency_collection_error_walk
        """
        bundle = self._settled(api)
        chargeback = bundle["chargebacks"][0]

        validate_error(
            api.offset_chargeback(
                chargeback["id"],
                factories.chargeback_offset(80000, chargeback["version"]),
                COLLECTIONS,
            ),
            ApiErrorId.OFFSET_EXCEEDS_RESERVE.value,
            422,
        )

        after = validate_success(
            api.get_agent_chargeback(chargeback["id"], COMPLIANCE), 200
        )
        assert after["offset_applied_cents"] == 0
        assert after["version"] == chargeback["version"]

    def test_a_partial_offset_advances_the_row_and_its_token(self, api):
        """An offset below the remainder is a legitimate self-loop.

        The PRD states: "An offset strictly smaller than the remainder moves the
        chargeback `PENDING` → `PARTIALLY_OFFSET`, or leaves an already partially
        offset chargeback in `PARTIALLY_OFFSET` — a legitimate self-loop that may
        repeat as often as the reserve allows, which is exactly why this write is
        protected by the expected-version check rather than by a state
        precondition."

        Design: Corner/errors/error_triggerable_power_of_attorney_and_deficiency_collection_error_walk
        """
        bundle = self._settled(api)
        chargeback = bundle["chargebacks"][0]

        partial = validate_success(
            api.offset_chargeback(
                chargeback["id"],
                factories.chargeback_offset(50000, chargeback["version"]),
                COLLECTIONS,
            ),
            200,
        )
        assert partial["status"] == "PARTIALLY_OFFSET"
        assert partial["offset_applied_cents"] == 50000
        assert partial["version"] == chargeback["version"] + 1

    def test_a_stale_token_between_two_legal_offsets_is_refused(self, api):
        """The token the first offset burned no longer authorises the second.

        The PRD states: "10. The supplied expected version matches the parent row's
        current `version` — otherwise `ERR_STALE_AGREEMENT_VERSION` on endorsement
        financing or `ERR_STALE_CHARGEBACK_VERSION` on a chargeback offset."

        Design: Corner/errors/error_triggerable_power_of_attorney_and_deficiency_collection_error_walk
        """
        bundle = self._settled(api)
        chargeback = bundle["chargebacks"][0]
        first_token = chargeback["version"]

        partial = validate_success(
            api.offset_chargeback(
                chargeback["id"],
                factories.chargeback_offset(50000, first_token),
                COLLECTIONS,
            ),
            200,
        )
        validate_error(
            api.offset_chargeback(
                chargeback["id"],
                factories.chargeback_offset(22000, first_token),
                COLLECTIONS,
            ),
            ApiErrorId.STALE_CHARGEBACK_VERSION.value,
            412,
        )

        settled = validate_success(
            api.offset_chargeback(
                chargeback["id"],
                factories.chargeback_offset(22000, partial["version"]),
                COLLECTIONS,
            ),
            200,
        )
        assert settled["status"] == "OFFSET"
        assert settled["offset_applied_cents"] == 72000
        assert settled["version"] == partial["version"] + 1

    def test_a_settled_chargeback_accepts_nothing_further(self, api):
        """Once the remainder is zero the row is closed to any further offset.

        The PRD states: "A chargeback already in `OFFSET` accepts nothing further
        and yields `ERR_CHARGEBACK_STATE_INVALID`."

        Design: Corner/errors/error_triggerable_power_of_attorney_and_deficiency_collection_error_walk
        """
        bundle = self._settled(api)
        chargeback = bundle["chargebacks"][0]

        partial = validate_success(
            api.offset_chargeback(
                chargeback["id"],
                factories.chargeback_offset(50000, chargeback["version"]),
                COLLECTIONS,
            ),
            200,
        )
        settled = validate_success(
            api.offset_chargeback(
                chargeback["id"],
                factories.chargeback_offset(22000, partial["version"]),
                COLLECTIONS,
            ),
            200,
        )
        validate_error(
            api.offset_chargeback(
                chargeback["id"],
                factories.chargeback_offset(100, settled["version"]),
                COLLECTIONS,
            ),
            ApiErrorId.CHARGEBACK_STATE_INVALID.value,
            409,
        )

    def test_the_agencys_books_agree_after_the_settlement(self, api):
        """The reserve fell by exactly the offsets and the exposure is gone.

        The PRD states: "Every offset, partial or final, adds `offset_amount_cents`
        to the chargeback's `offset_applied_cents`, subtracts the same amount from
        the agency's `chargeback_reserve_balance_cents`, recomputes
        `outstanding_chargeback_cents`, and advances the chargeback's `version`."

        Design: Corner/errors/error_triggerable_power_of_attorney_and_deficiency_collection_error_walk
        """
        bundle = self._settled(api)
        chargeback = bundle["chargebacks"][0]
        partial = validate_success(
            api.offset_chargeback(
                chargeback["id"],
                factories.chargeback_offset(50000, chargeback["version"]),
                COLLECTIONS,
            ),
            200,
        )
        validate_success(
            api.offset_chargeback(
                chargeback["id"],
                factories.chargeback_offset(22000, partial["version"]),
                COLLECTIONS,
            ),
            200,
        )

        agent = validate_success(api.get_agent(bundle["agent_id"], COMPLIANCE), 200)
        assert agent["chargeback_reserve_balance_cents"] == 100000 - 72000 == 28000
        assert agent["outstanding_chargeback_cents"] == 0
        assert agent["status"] == "ACTIVE", (
            "72000 of exposure never reached the 500000 liability cap, so the "
            "agency was never suspended"
        )

    def test_the_agency_can_read_its_own_settled_chargeback(self, api):
        """The party that owes the money can inspect the row that says so.

        The PRD states: "Chargebacks can be listed by agency, note or `status` and
        read individually, and an agency may inspect its own exposure through both
        surfaces."

        Design: Corner/errors/error_triggerable_power_of_attorney_and_deficiency_collection_error_walk
        """
        bundle = self._settled(api)
        chargeback = bundle["chargebacks"][0]
        partial = validate_success(
            api.offset_chargeback(
                chargeback["id"],
                factories.chargeback_offset(50000, chargeback["version"]),
                COLLECTIONS,
            ),
            200,
        )
        validate_success(
            api.offset_chargeback(
                chargeback["id"],
                factories.chargeback_offset(22000, partial["version"]),
                COLLECTIONS,
            ),
            200,
        )

        own = validate_success(
            api.get_agent_chargeback(chargeback["id"], bundle["agent_headers"]), 200
        )
        assert own["status"] == "OFFSET"
        assert own["offset_applied_cents"] == 72000

        rows, meta = validate_paginated(
            api.list_agent_chargebacks(
                bundle["agent_headers"],
                {"producer_agent_id": bundle["agent_id"], "limit": 50},
            )
        )
        assert meta["total_count"] == 1
        assert rows[0]["id"] == chargeback["id"]


class TestStatutoryCeilingAndIncoherentFilterPair:
    """The exception mechanism is bounded by the very number it exists to bend, and
    a query naming two rows that do not know each other is refused rather than
    answered."""

    def _two_notes(self, api):
        """Two DRAFT notes under one regime, each carrying one policy.

        Because each note owns a policy, a policy of the second note can be paired
        with the first one to build a query that names nothing coherent.
        """
        ctx = fixtures.origination_context(
            api,
            insured_payload=factories.insured(
                legal_name="Cascade Logistics Inc", email="ap@cascade.example"
            ),
        )
        note_a = fixtures.draft_agreement(
            api,
            ctx,
            policies=[
                factories.financed_policy(
                    ctx["insurer_id"],
                    policy_number="MC-RC-A",
                    gross_premium_cents=600000,
                )
            ],
        )
        note_b = fixtures.draft_agreement(
            api,
            ctx,
            policies=[
                factories.financed_policy(
                    ctx["insurer_id"],
                    policy_number="MC-RC-B",
                    gross_premium_cents=400000,
                )
            ],
        )
        ctx["a"] = note_a
        ctx["b"] = note_b
        return ctx

    def test_the_regime_caps_the_rate_and_the_note_starts_unexcepted(self, api):
        """The ceiling is on file and the fresh note carries no exception.

        The PRD states: "while `quote_basis`, `activated_at`,
        `restructured_from_agreement_id`, `approved_service_fee_cap_cents` and
        `approved_annual_rate_bps` are all null and `rate_exception_approved` is
        false."

        Design: Corner/errors/error_triggerable_statutory_ceiling_and_incoherent_filter_pair
        """
        ctx = self._two_notes(api)

        assert ctx["rule"]["max_annual_rate_bps"] == 1800
        created = ctx["a"]["agreement"]
        assert created["rate_exception_approved"] is False
        assert created["approved_annual_rate_bps"] is None
        assert created["approved_service_fee_cap_cents"] is None

    def test_one_basis_point_over_the_ceiling_is_still_over(self, api):
        """1801 against a ceiling of 1800 is refused.

        The PRD states: "An `override_annual_rate_bps` above the regime's
        `max_annual_rate_bps` is refused with `ERR_RATE_ABOVE_STATE_MAXIMUM` (HTTP
        422) — the statutory ceiling is never negotiable."

        Design: Corner/errors/error_triggerable_statutory_ceiling_and_incoherent_filter_pair
        """
        ctx = self._two_notes(api)

        validate_error(
            api.approve_rate_exception(
                ctx["a"]["agreement_id"],
                factories.rate_exception(
                    override_annual_rate_bps=1801,
                    justification="national account concession, one basis point over",
                ),
                COMPLIANCE_APPROVER,
            ),
            ApiErrorId.RATE_ABOVE_STATE_MAXIMUM.value,
            422,
        )

    def test_an_aggressive_override_reports_the_same_ceiling(self, api):
        """3000 basis points is refused by the same rule, not a different one.

        The PRD states: "28. An approved rate exception does not exceed the
        statutory ceiling — otherwise `ERR_RATE_ABOVE_STATE_MAXIMUM`, on
        rate-exception approval."

        Design: Corner/errors/error_triggerable_statutory_ceiling_and_incoherent_filter_pair
        """
        ctx = self._two_notes(api)

        validate_error(
            api.approve_rate_exception(
                ctx["a"]["agreement_id"],
                factories.rate_exception(
                    override_annual_rate_bps=3000,
                    justification="aggressive override well past the ceiling",
                ),
                COMPLIANCE_APPROVER,
            ),
            ApiErrorId.RATE_ABOVE_STATE_MAXIMUM.value,
            422,
        )

    def test_an_override_exactly_at_the_ceiling_is_granted(self, api):
        """Equality is inside the ceiling, and the approver is recorded.

        The PRD states: "It sets `rate_exception_approved` to true, records the
        approver as `rate_exception_approved_by_user_id`, copies
        `override_service_fee_cents` into `approved_service_fee_cap_cents` and
        `override_annual_rate_bps` into `approved_annual_rate_bps` when each is
        supplied, and advances the note's `version`."

        Design: Corner/errors/error_triggerable_statutory_ceiling_and_incoherent_filter_pair
        """
        ctx = self._two_notes(api)

        granted = validate_success(
            api.approve_rate_exception(
                ctx["a"]["agreement_id"],
                factories.rate_exception(
                    override_annual_rate_bps=1800,
                    justification="priced at the statutory ceiling",
                ),
                COMPLIANCE_APPROVER,
            ),
            200,
        )
        assert granted["rate_exception_approved"] is True
        assert granted["approved_annual_rate_bps"] == 1800
        assert granted["rate_exception_approved_by_user_id"] == "compliance-approver"

    def test_only_the_granted_approval_advanced_the_note(self, api):
        """Two refusals wrote nothing, so the version moved exactly once.

        The PRD states: "`version` starts at 1 when the row is created and
        increases by exactly 1 on every mutation of that row; `updated_at` is
        refreshed to the logical-clock instant on the same mutation."

        Design: Corner/errors/error_triggerable_statutory_ceiling_and_incoherent_filter_pair
        """
        ctx = self._two_notes(api)
        before = fixtures.agreement_version(api, ctx["a"]["agreement_id"])
        assert before == 2, (
            "the note was created and then had one policy attached, and both are "
            "writes to the note itself"
        )

        for over in (1801, 3000):
            validate_error(
                api.approve_rate_exception(
                    ctx["a"]["agreement_id"],
                    factories.rate_exception(
                        override_annual_rate_bps=over,
                        justification="above the statutory ceiling",
                    ),
                    COMPLIANCE_APPROVER,
                ),
                ApiErrorId.RATE_ABOVE_STATE_MAXIMUM.value,
                422,
            )
        granted = validate_success(
            api.approve_rate_exception(
                ctx["a"]["agreement_id"],
                factories.rate_exception(
                    override_annual_rate_bps=1800,
                    justification="priced at the statutory ceiling",
                ),
                COMPLIANCE_APPROVER,
            ),
            200,
        )

        assert granted["version"] == before + 1 == 3, (
            "exactly one of the three approval attempts was a mutation"
        )

    def test_omitting_the_fee_override_leaves_the_fee_cap_alone(self, api):
        """Only the field that was supplied is copied onto the note.

        The PRD states: "The approval carries a mandatory `justification` and either
        or both of `override_service_fee_cents` and `override_annual_rate_bps`."

        Design: Corner/errors/error_triggerable_statutory_ceiling_and_incoherent_filter_pair
        """
        ctx = self._two_notes(api)
        validate_success(
            api.approve_rate_exception(
                ctx["a"]["agreement_id"],
                factories.rate_exception(
                    override_annual_rate_bps=1800,
                    justification="priced at the statutory ceiling",
                ),
                COMPLIANCE_APPROVER,
            ),
            200,
        )

        read_back = fixtures.read_agreement(api, ctx["a"]["agreement_id"])
        assert read_back["rate_exception_approved"] is True
        assert read_back["approved_annual_rate_bps"] == 1800
        assert read_back["approved_service_fee_cap_cents"] is None

    def test_an_incoherent_agreement_and_policy_pair_is_refused(self, api):
        """A policy of the second note cannot be read through the first one.

        The PRD states: "This applies when an attestation is filed against a policy
        whose agreement is not the one whose verification cycle is open, when a
        carrier return names an `agreement_id` that is not the `agreement_id` of the
        request's policy, and — deliberately — when a listing of carrier
        cancellation requests supplies `agreement_id` and `policy_id` together as an
        incoherent pair."

        Design: Corner/errors/error_triggerable_statutory_ceiling_and_incoherent_filter_pair
        """
        ctx = self._two_notes(api)

        validate_error(
            api.list_carrier_cancellation_requests(
                COMPLIANCE,
                {
                    "agreement_id": ctx["a"]["agreement_id"],
                    "policy_id": ctx["b"]["policy_id"],
                    "limit": 50,
                },
            ),
            ApiErrorId.POLICY_AGREEMENT_MISMATCH.value,
            409,
        )

    def test_the_coherent_pair_is_answered_with_an_empty_page(self, api):
        """An empty page and a refusal are different answers.

        The PRD states: "The ledger refuses an incoherent query rather than
        answering it with an empty page."

        Design: Corner/errors/error_triggerable_statutory_ceiling_and_incoherent_filter_pair
        """
        ctx = self._two_notes(api)

        _, meta = validate_paginated(
            api.list_carrier_cancellation_requests(
                COMPLIANCE,
                {
                    "agreement_id": ctx["a"]["agreement_id"],
                    "policy_id": ctx["a"]["policy_id"],
                    "limit": 50,
                },
            )
        )
        assert meta["total_count"] == 0
        assert meta["has_more"] is False

    def test_a_note_filtered_on_its_own_is_answered_too(self, api):
        """The single-key filter needs no coherence check at all.

        The PRD states: "Requests may be listed and read by analysts, compliance
        officers and carriers, filtered by note, policy or `status`."

        Design: Corner/errors/error_triggerable_statutory_ceiling_and_incoherent_filter_pair
        """
        ctx = self._two_notes(api)

        _, meta = validate_paginated(
            api.list_carrier_cancellation_requests(
                COMPLIANCE, {"agreement_id": ctx["b"]["agreement_id"], "limit": 50}
            )
        )
        assert meta["total_count"] == 0
        assert meta["has_more"] is False

        _, by_policy = validate_paginated(
            api.list_carrier_cancellation_requests(
                COMPLIANCE, {"policy_id": ctx["b"]["policy_id"], "limit": 50}
            )
        )
        assert by_policy["total_count"] == 0
