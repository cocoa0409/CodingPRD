"""Access-control corners: the two operator roles own disjoint halves of the
platform and the whole happy path proves it, the three entity-backed roles are
confined to the rows that name them, authentication and authorization are settled
before the server admits whether a row even exists, and the two mandatory
two-person controls compare identities rather than roles.
"""

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    factories,
    fixtures,
    late_fee_cents,
    rule_of_78_rebate_cents,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.test_users import (
    ANALYST_ORIGIN,
    ANALYST_NOTICE,
    COMPLIANCE,
    COMPLIANCE_APPROVER,
    NO_AUTH_HEADERS,
    make_analyst_headers,
    make_compliance_headers,
    make_insured_headers,
    make_insurer_headers,
    make_producer_agent_headers,
)

# A second execution handle, so that the analyst who reaches for the policies is
# never the analyst who issued the notice.
ANALYST_EXECUTE = make_analyst_headers("analyst-execute")


class TestExclusiveOperationsAndAuthorizationBeforeExistence:
    """The statutory surface is written only by compliance and the paper only by
    the analyst, and the refusals pin the two orderings at the top of the
    precedence list."""

    def _exclusive_path(self, api):
        """The whole origination walked with each call made by the role that
        exclusively owns it."""
        fixtures.set_clock(api, "2026-08-15T00:00:00Z")
        rule = validate_success(
            api.create_state_rate_rule(factories.tx_state_rate_rule(), COMPLIANCE), 201
        )
        lic = validate_success(
            api.create_license(
                rule["id"],
                factories.license_payload(license_number="PFC-TX-001"),
                COMPLIANCE,
            ),
            201,
        )
        insured = validate_success(
            api.create_insured(
                factories.insured(
                    legal_name="Cascade Logistics Inc", email="ap@cascade.example"
                ),
                ANALYST_ORIGIN,
            ),
            201,
        )
        agent = validate_success(
            api.create_agent(factories.producer_agent(), COMPLIANCE), 201
        )
        insurer = validate_success(
            api.create_insurer(factories.insurer(), COMPLIANCE), 201
        )
        note = validate_success(
            api.create_agreement(
                factories.agreement(insured["id"], agent["id"], rule["id"]),
                ANALYST_ORIGIN,
            ),
            201,
        )
        policy = validate_success(
            api.attach_policy(
                note["id"],
                factories.financed_policy(insurer["id"], policy_number="MC-RB-1"),
                ANALYST_ORIGIN,
            ),
            201,
        )
        validate_success(api.submit_agreement(note["id"], ANALYST_ORIGIN), 200)
        carrier_headers = make_insurer_headers(insurer["id"])
        agency_headers = make_producer_agent_headers(agent["id"])
        borrower_headers = make_insured_headers(insured["id"])
        carrier_voice = validate_success(
            api.create_verification(
                policy["id"], factories.confirmed_verification(), carrier_headers
            ),
            201,
        )
        agency_voice = validate_success(
            api.create_verification(
                policy["id"], factories.confirmed_verification(), agency_headers
            ),
            201,
        )
        activated = validate_success(
            api.activate_agreement(note["id"], ANALYST_ORIGIN), 200
        )
        return {
            "rule_id": rule["id"],
            "license_id": lic["id"],
            "insured_id": insured["id"],
            "agent_id": agent["id"],
            "insurer_id": insurer["id"],
            "agreement_id": note["id"],
            "policy_id": policy["id"],
            "carrier_headers": carrier_headers,
            "agency_headers": agency_headers,
            "borrower_headers": borrower_headers,
            "carrier_voice": carrier_voice,
            "agency_voice": agency_voice,
            "activated": activated,
        }

    def _paid_once(self, api):
        """The same note with the borrower's first installment paid."""
        ctx = self._exclusive_path(api)
        ctx["payment"] = validate_success(
            api.create_payment(
                ctx["agreement_id"],
                factories.payment(89941, "2026-08-15"),
                ctx["borrower_headers"],
            ),
            201,
        )
        return ctx

    def test_every_exclusive_operation_is_accepted_from_its_owning_role(self, api):
        """Compliance writes the statute, the analyst writes the paper, and the
        two counterparties attest — and the note funds.

        The PRD states: "A `FinanceAnalyst` originates notes, attaches the policies
        being financed, submits and activates agreements, posts and reverses
        payments, issues notices of intent to cancel, exercises the power of
        attorney, finances endorsements and restructures accounts. A
        `ComplianceOfficer` owns the statutory surface — state rate regimes,
        licenses, agency onboarding and suspension, carrier registration, rate
        exceptions, late-fee waivers, the servicing run and chargeback offsets —
        and may never originate or activate a note."  It also states: "`party`
        becomes `INSURER` when the caller acts as `Insurer` and `PRODUCER_AGENT`
        when the caller acts as `ProducerAgent`; `party_user_id` is taken from
        `X-User-ID`, so it equals the policy's `insurer_id` for a carrier filing
        and the agreement's `producer_agent_id` for an agency filing".

        Design: Corner/rbac/exclusive_operations_role_matrix_and_authorization_before_existence
        """
        ctx = self._exclusive_path(api)

        assert ctx["activated"]["status"] == "ACTIVE", (
            "every call in the chain was made by the single role that owns it"
        )
        assert ctx["carrier_voice"]["id"] is not None
        assert ctx["agency_voice"]["id"] is not None
        assert ctx["carrier_voice"]["party"] == "INSURER"
        assert ctx["carrier_voice"]["party_user_id"] == ctx["insurer_id"]
        assert ctx["agency_voice"]["party"] == "PRODUCER_AGENT"
        assert ctx["agency_voice"]["party_user_id"] == ctx["agent_id"]
        assert ctx["activated"]["total_of_payments_cents"] == 539650
        assert ctx["activated"]["originated_by_user_id"] == "analyst-origin"

    def test_the_borrower_pays_its_own_note_and_reads_its_own_schedule(self, api):
        """The Insured is a first-class caller on the money and the schedule.

        The PRD states: "An `Insured` is the borrower; it pays the note and reads
        its own schedule, payments, late fees, notices and payoff quote."

        Design: Corner/rbac/exclusive_operations_role_matrix_and_authorization_before_existence
        """
        ctx = self._paid_once(api)

        assert ctx["payment"]["status"] == "POSTED"
        assert ctx["payment"]["applied_finance_charge_cents"] == 6275
        assert ctx["payment"]["applied_principal_cents"] == 83666
        assert ctx["payment"]["applied_late_fee_cents"] == 0
        assert ctx["payment"]["applied_unapplied_cents"] == 0

        rows, meta = validate_paginated(
            api.list_installments(
                ctx["agreement_id"], ctx["borrower_headers"], {"limit": 50}
            )
        )
        assert meta["total_count"] == 6
        first = next(row for row in rows if row["installment_number"] == 1)
        assert first["status"] == "PAID", (
            "89941 covers the whole first installment, finance charge first"
        )
        assert first["paid_cents"] == 89941

    def test_the_borrower_may_ask_what_it_would_take_to_close_the_note(self, api):
        """One retired installment moves r from six to five, and the quote with it.

        The PRD states: "Let *r* be the number of installments not yet retired:
        `installment_count` minus the count of the note's installments whose
        `status` is `PAID`." and "The net payoff is then `principal_balance_cents`
        plus `unpaid_finance_charge_cents`, minus the rebate, plus
        `late_fee_balance_cents`, minus `unapplied_credit_cents`."

        Design: Corner/rbac/exclusive_operations_role_matrix_and_authorization_before_existence
        """
        ctx = self._paid_once(api)

        quote = validate_success(
            api.get_payoff_quote(ctx["agreement_id"], ctx["borrower_headers"]), 200
        )

        assert quote["as_of_date"] == "2026-08-15"
        assert quote["rebate_method"] == "RULE_OF_78"
        assert quote["gross_balance_cents"] == 418334 + 31375 == 449709
        assert quote["unearned_finance_charge_rebate_cents"] == rule_of_78_rebate_cents(
            37650, 5, 6
        ) == 26893, "five installments unretired, not six"
        assert quote["outstanding_late_fee_cents"] == 0
        assert quote["unapplied_credit_cents"] == 0
        assert quote["net_payoff_cents"] == 449709 - 26893 == 422816

    def test_the_analyst_cannot_touch_the_statutory_surface(self, api):
        """Writing a regime, running the sweep and suspending a licence are all
        compliance verbs.

        The PRD states: "A header value outside that set, or a role that is not
        listed among the authorized roles of the operation being called, is
        rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."

        Design: Corner/rbac/exclusive_operations_role_matrix_and_authorization_before_existence
        """
        ctx = self._exclusive_path(api)

        validate_error(
            api.create_state_rate_rule(
                factories.state_rate_rule("NV"), ANALYST_ORIGIN
            ),
            ApiErrorId.UNAUTHORIZED_ROLE,
            403,
        )
        validate_error(
            api.run_servicing(ANALYST_ORIGIN), ApiErrorId.UNAUTHORIZED_ROLE, 403
        )
        validate_error(
            api.suspend_license(ctx["license_id"], ANALYST_ORIGIN),
            ApiErrorId.UNAUTHORIZED_ROLE,
            403,
        )

        rows, meta = validate_paginated(
            api.list_licenses(ctx["rule_id"], COMPLIANCE, {"limit": 50})
        )
        assert meta["total_count"] == 1
        assert rows[0]["status"] == "ACTIVE", "the refused suspension changed nothing"

    def test_compliance_may_neither_originate_nor_activate_a_note(self, api):
        """The role that sets the rates never writes the paper.

        The PRD states: "A `ComplianceOfficer` owns the statutory surface — state
        rate regimes, licenses, agency onboarding and suspension, carrier
        registration, rate exceptions, late-fee waivers, the servicing run and
        chargeback offsets — and may never originate or activate a note."

        Design: Corner/rbac/exclusive_operations_role_matrix_and_authorization_before_existence
        """
        ctx = self._exclusive_path(api)

        validate_error(
            api.create_agreement(
                factories.agreement(
                    ctx["insured_id"], ctx["agent_id"], ctx["rule_id"]
                ),
                COMPLIANCE,
            ),
            ApiErrorId.UNAUTHORIZED_ROLE,
            403,
        )
        validate_error(
            api.activate_agreement(ctx["agreement_id"], COMPLIANCE),
            ApiErrorId.UNAUTHORIZED_ROLE,
            403,
        )

        _, meta = validate_paginated(api.list_agreements(COMPLIANCE, {"limit": 50}))
        assert meta["total_count"] == 1, "the refused origination wrote no note"

    def test_the_three_counterparty_roles_are_confined_to_their_own_verbs(self, api):
        """A carrier cannot exercise the power of attorney, a borrower cannot
        attest a premium, and an agency cannot pay the note.

        The PRD states: "Five roles exist, and their names are spelled exactly as
        follows: `FinanceAnalyst`, `ComplianceOfficer`, `ProducerAgent`, `Insurer`,
        and `Insured`. A header value outside that set, or a role that is not
        listed among the authorized roles of the operation being called, is
        rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."

        Design: Corner/rbac/exclusive_operations_role_matrix_and_authorization_before_existence
        """
        ctx = self._exclusive_path(api)

        validate_error(
            api.execute_cancellation(ctx["agreement_id"], ctx["carrier_headers"]),
            ApiErrorId.UNAUTHORIZED_ROLE,
            403,
        )
        validate_error(
            api.create_verification(
                ctx["policy_id"],
                factories.confirmed_verification(),
                ctx["borrower_headers"],
            ),
            ApiErrorId.UNAUTHORIZED_ROLE,
            403,
        )
        validate_error(
            api.create_payment(
                ctx["agreement_id"],
                factories.payment(1000, "2026-08-15"),
                ctx["agency_headers"],
            ),
            ApiErrorId.UNAUTHORIZED_ROLE,
            403,
        )

    def test_the_role_refusal_leaves_the_ledger_untouched(self, api):
        """Three refusals, and not one row moved.

        The PRD states: "Any single request can violate several rules at once, and
        the platform must always report the same one."

        Design: Corner/rbac/exclusive_operations_role_matrix_and_authorization_before_existence
        """
        ctx = self._exclusive_path(api)
        before = fixtures.read_agreement(api, ctx["agreement_id"])

        validate_error(
            api.execute_cancellation(ctx["agreement_id"], ctx["carrier_headers"]),
            ApiErrorId.UNAUTHORIZED_ROLE,
            403,
        )
        validate_error(
            api.create_payment(
                ctx["agreement_id"],
                factories.payment(1000, "2026-08-15"),
                ctx["agency_headers"],
            ),
            ApiErrorId.UNAUTHORIZED_ROLE,
            403,
        )

        after = fixtures.read_agreement(api, ctx["agreement_id"])
        assert after["version"] == before["version"]
        assert after["status"] == "ACTIVE"
        assert after["delinquency_stage"] == "CURRENT"
        assert after["principal_balance_cents"] == 502000
        _, meta = validate_paginated(
            api.list_payments(ctx["agreement_id"], COMPLIANCE, {"limit": 50})
        )
        assert meta["total_count"] == 0, "the agency's payment was never written"

    def test_the_wrong_role_learns_nothing_about_a_row_that_does_not_exist(self, api):
        """The same ghost late-fee id answers 403 to the analyst and 404 to
        compliance.

        The PRD states: "2. The role is one of the five defined roles and is
        authorized for the operation — otherwise `ERR_UNAUTHORIZED_ROLE`." and "3.
        Every identifier in the path resolves, left to right — otherwise the
        corresponding not-found code from section 2.7."

        Design: Corner/rbac/exclusive_operations_role_matrix_and_authorization_before_existence
        """
        self._exclusive_path(api)

        validate_error(
            api.waive_late_fee(
                NON_EXISTENT_UUID,
                factories.waiver(justification="wrong role, ghost id"),
                ANALYST_ORIGIN,
            ),
            ApiErrorId.UNAUTHORIZED_ROLE,
            403,
        )
        validate_error(
            api.waive_late_fee(
                NON_EXISTENT_UUID,
                factories.waiver(justification="right role, ghost id"),
                COMPLIANCE,
            ),
            ApiErrorId.LATE_FEE_NOT_FOUND,
            404,
        )

    def test_missing_headers_are_refused_before_the_role_is_considered(self, api):
        """With no identity at all, both a permitted read and a forbidden write
        answer 401.

        The PRD states: "Every request to the API must carry two headers:
        `X-User-ID`, identifying the caller, and `X-User-Role`, naming the capacity
        in which the caller acts. If either header is absent or empty, the request
        is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/rbac/exclusive_operations_role_matrix_and_authorization_before_existence
        """
        ctx = self._exclusive_path(api)

        validate_error(
            api.get_agreement(ctx["agreement_id"], NO_AUTH_HEADERS),
            ApiErrorId.UNAUTHENTICATED,
            401,
        )
        validate_error(
            api.run_servicing(NO_AUTH_HEADERS), ApiErrorId.UNAUTHENTICATED, 401
        )

    def test_the_shared_reads_answer_compliance_with_the_same_rows(self, api):
        """Reads that several roles share really are shared.

        The PRD states: "The ordering rationale is that authentication precedes
        existence, existence precedes ownership, ownership precedes optimistic
        concurrency, concurrency precedes state preconditions, and inside the
        business band the statutory and licensing checks — which can void the
        transaction for the finance company altogether — run before referential,
        temporal and finally fiscal checks."

        Design: Corner/rbac/exclusive_operations_role_matrix_and_authorization_before_existence
        """
        ctx = self._paid_once(api)

        notes, notes_meta = validate_paginated(
            api.list_agreements(COMPLIANCE, {"limit": 50})
        )
        assert notes_meta["total_count"] == 1
        assert notes[0]["id"] == ctx["agreement_id"]

        payments, payments_meta = validate_paginated(
            api.list_payments(ctx["agreement_id"], COMPLIANCE, {"limit": 50})
        )
        assert payments_meta["total_count"] == 1
        assert payments[0]["id"] == ctx["payment"]["id"]

        borrower_view = validate_success(
            api.get_agreement(ctx["agreement_id"], ctx["borrower_headers"]), 200
        )
        assert borrower_view["id"] == ctx["agreement_id"], (
            "the borrower reads the same row compliance just read"
        )


class TestEntityBackedRolesAreConfinedToTheirOwnRows:
    """Two borrowers, two agencies and two carriers, so that every ownership edge
    can be crossed with an otherwise perfectly legal request."""

    def _two_books(self, api):
        """Note NX belongs to borrower X, agency A and carrier M; note NY to
        borrower Y, agency B and carrier N.  Both are submitted."""
        regime = fixtures.create_tx_regime(api)
        fixtures.set_clock(api, "2026-08-15T00:00:00Z")
        rule_id = regime["rule_id"]
        borrower_x = validate_success(
            api.create_insured(
                factories.insured(
                    legal_name="Cascade Logistics Inc", email="ap@cascade.example"
                ),
                ANALYST_ORIGIN,
            ),
            201,
        )
        borrower_y = validate_success(
            api.create_insured(
                factories.insured(
                    legal_name="Ridgeline Freight LLC", email="ap@ridgeline.example"
                ),
                ANALYST_ORIGIN,
            ),
            201,
        )
        agency_a = validate_success(
            api.create_agent(factories.producer_agent(), COMPLIANCE), 201
        )
        agency_b = validate_success(
            api.create_agent(
                factories.producer_agent(
                    agency_name="Pecos Agency Group",
                    agent_commission_bps=1000,
                    chargeback_basis="RESERVE_CAPPED",
                    chargeback_liability_cap_cents=300000,
                    initial_reserve_balance_cents=80000,
                ),
                COMPLIANCE,
            ),
            201,
        )
        carrier_m = validate_success(
            api.create_insurer(factories.insurer(), COMPLIANCE), 201
        )
        carrier_n = validate_success(
            api.create_insurer(
                factories.insurer(carrier_name="Northgate Indemnity", naic_code="10789"),
                COMPLIANCE,
            ),
            201,
        )
        note_x = validate_success(
            api.create_agreement(
                factories.agreement(borrower_x["id"], agency_a["id"], rule_id),
                ANALYST_ORIGIN,
            ),
            201,
        )
        policy_x = validate_success(
            api.attach_policy(
                note_x["id"],
                factories.financed_policy(carrier_m["id"], policy_number="MC-OW-X"),
                ANALYST_ORIGIN,
            ),
            201,
        )
        validate_success(api.submit_agreement(note_x["id"], ANALYST_ORIGIN), 200)
        note_y = validate_success(
            api.create_agreement(
                factories.agreement(borrower_y["id"], agency_b["id"], rule_id),
                ANALYST_ORIGIN,
            ),
            201,
        )
        policy_y = validate_success(
            api.attach_policy(
                note_y["id"],
                factories.financed_policy(carrier_n["id"], policy_number="NG-OW-Y"),
                ANALYST_ORIGIN,
            ),
            201,
        )
        validate_success(api.submit_agreement(note_y["id"], ANALYST_ORIGIN), 200)
        return {
            "nx": note_x["id"],
            "ny": note_y["id"],
            "px": policy_x["id"],
            "py": policy_y["id"],
            "x_id": borrower_x["id"],
            "y_id": borrower_y["id"],
            "a_id": agency_a["id"],
            "b_id": agency_b["id"],
            "m_id": carrier_m["id"],
            "n_id": carrier_n["id"],
            "x": make_insured_headers(borrower_x["id"]),
            "y": make_insured_headers(borrower_y["id"]),
            "a": make_producer_agent_headers(agency_a["id"]),
            "b": make_producer_agent_headers(agency_b["id"]),
            "m": make_insurer_headers(carrier_m["id"]),
            "n": make_insurer_headers(carrier_n["id"]),
        }

    def _active_nx(self, api):
        """The same two books, with note NX attested by its rightful parties and
        funded."""
        books = self._two_books(api)
        books["carrier_voice"] = validate_success(
            api.create_verification(
                books["px"], factories.confirmed_verification(), books["m"]
            ),
            201,
        )
        books["agency_voice"] = validate_success(
            api.create_verification(
                books["px"], factories.confirmed_verification(), books["a"]
            ),
            201,
        )
        books["activated"] = validate_success(
            api.activate_agreement(books["nx"], ANALYST_ORIGIN), 200
        )
        return books

    def test_the_borrower_reads_the_note_that_names_it(self, api):
        """Holding the Insured role means nothing on its own; naming the row does.

        The PRD states: "When `X-User-Role` is `Insured`, `X-User-ID` is the `id` of
        the acting `Insured`, and ownership checks compare the addressed
        agreement's `insured_id` to `X-User-ID`."

        Design: Corner/rbac/cross_role_denial_entity_backed_roles_are_confined_to_their_own_rows
        """
        books = self._two_books(api)

        own = validate_success(api.get_agreement(books["nx"], books["x"]), 200)

        assert own["id"] == books["nx"]
        assert own["insured_id"] == books["x_id"]
        assert own["producer_agent_id"] == books["a_id"]

    def test_a_borrower_cannot_read_another_borrowers_note(self, api):
        """The role is right, the identity is not.

        The PRD states: "An entity-backed caller that addresses a resource it does
        not own is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403). This ownership
        gate guards four operations specifically: reading a single agreement,
        posting a payment against an agreement, filing an endorsement on a policy,
        and posting a carrier return against a carrier cancellation request."

        Design: Corner/rbac/cross_role_denial_entity_backed_roles_are_confined_to_their_own_rows
        """
        books = self._two_books(api)

        validate_error(
            api.get_agreement(books["ny"], books["x"]),
            ApiErrorId.NOT_RESOURCE_OWNER,
            403,
        )

        assert validate_success(api.get_agreement(books["ny"], books["y"]), 200)[
            "id"
        ] == books["ny"], "borrower Y reads the very row borrower X was refused"

    def test_a_carrier_that_did_not_issue_the_policy_has_no_standing(self, api):
        """Attestation standing is stricter than ownership and has its own code.

        The PRD states: "An attestation is filed against a single policy by an
        `Insurer` or a `ProducerAgent`, and standing is checked before anything else
        about the filing: a caller acting as `Insurer` must present an `X-User-ID`
        equal to the policy's `insurer_id`, and a caller acting as `ProducerAgent`
        must present an `X-User-ID` equal to the `producer_agent_id` of the policy's
        agreement."

        Design: Corner/rbac/cross_role_denial_entity_backed_roles_are_confined_to_their_own_rows
        """
        books = self._two_books(api)

        validate_error(
            api.create_verification(
                books["px"], factories.confirmed_verification(), books["n"]
            ),
            ApiErrorId.VERIFIER_NOT_AUTHORIZED,
            403,
        )

        assert fixtures.read_verifications(api, books["px"]) == [], (
            "carrier N wrote no attestation on carrier M's policy"
        )

    def test_an_agency_that_did_not_produce_the_note_has_no_standing(self, api):
        """The agency's standing runs through the agreement, not the policy.

        The PRD states: "A caller without standing is refused with
        `ERR_VERIFIER_NOT_AUTHORIZED` (HTTP 403), and a policy addressed alongside
        an agreement whose verification cycle it does not belong to is refused with
        `ERR_POLICY_AGREEMENT_MISMATCH`."

        Design: Corner/rbac/cross_role_denial_entity_backed_roles_are_confined_to_their_own_rows
        """
        books = self._two_books(api)

        validate_error(
            api.create_verification(
                books["px"], factories.confirmed_verification(), books["b"]
            ),
            ApiErrorId.VERIFIER_NOT_AUTHORIZED,
            403,
        )

        policy = fixtures.read_policy(api, books["px"])
        assert policy["status"] == "PENDING_VERIFICATION"
        assert policy["verified_premium_cents"] is None

    def test_the_rightful_parties_are_accepted_on_the_identical_call(self, api):
        """The same payload from the two parties that do have standing funds the
        note.

        The PRD states: "`party_user_id` is taken from `X-User-ID`, so it equals the
        policy's `insurer_id` for a carrier filing and the agreement's
        `producer_agent_id` for an agency filing".

        Design: Corner/rbac/cross_role_denial_entity_backed_roles_are_confined_to_their_own_rows
        """
        books = self._active_nx(api)

        assert books["carrier_voice"]["party_user_id"] == books["m_id"]
        assert books["agency_voice"]["party_user_id"] == books["a_id"]
        assert books["activated"]["status"] == "ACTIVE"
        assert fixtures.read_policy(api, books["px"])["status"] == "VERIFIED"

    def test_only_the_borrower_named_on_the_note_may_pay_it(self, api):
        """Identical money from the wrong borrower is refused, from the right one
        posted.

        The PRD states: "An `Insured` may read and pay only its own agreement; a
        `ProducerAgent` may read only an agreement that names it and may endorse
        only a policy hanging off such an agreement; an `Insurer` may post a return
        only on a request whose policy names it."

        Design: Corner/rbac/cross_role_denial_entity_backed_roles_are_confined_to_their_own_rows
        """
        books = self._active_nx(api)
        payload = factories.payment(89941, "2026-08-15")

        validate_error(
            api.create_payment(books["nx"], payload, books["y"]),
            ApiErrorId.NOT_RESOURCE_OWNER,
            403,
        )

        posted = validate_success(
            api.create_payment(books["nx"], payload, books["x"]), 201
        )
        assert posted["status"] == "POSTED"
        assert posted["applied_principal_cents"] == 83666
        assert posted["applied_finance_charge_cents"] == 6275

    def test_only_the_producing_agency_may_endorse_the_notes_policy(self, api):
        """The endorsement edge is guarded at priority 5, not at the role gate.

        The PRD states: "5. An entity-backed role owns the addressed resource —
        otherwise `ERR_NOT_RESOURCE_OWNER`. This guards reading one agreement,
        posting a payment, filing an endorsement and posting a carrier return."

        Design: Corner/rbac/cross_role_denial_entity_backed_roles_are_confined_to_their_own_rows
        """
        books = self._active_nx(api)
        payload = factories.endorsement(60000, effective_date="2026-09-15")

        validate_error(
            api.create_endorsement(books["px"], payload, books["b"]),
            ApiErrorId.NOT_RESOURCE_OWNER,
            403,
        )

        filed = validate_success(
            api.create_endorsement(books["px"], payload, books["a"]), 201
        )
        assert filed["amount_cents"] == 60000
        assert filed["status"] == "PENDING"

        rows = fixtures.read_endorsements(api, books["px"])
        assert len(rows) == 1, "the refused filing left no row"
        assert rows[0]["id"] == filed["id"]

    def test_nothing_leaked_across_the_two_books(self, api):
        """Each borrower's collection contains only its own rows, and the note
        nobody attested has no attestations.

        The PRD states: "Two of these roles are operator identities and three are
        entity-backed."

        Design: Corner/rbac/cross_role_denial_entity_backed_roles_are_confined_to_their_own_rows
        """
        books = self._active_nx(api)
        validate_success(
            api.create_payment(
                books["nx"], factories.payment(89941, "2026-08-15"), books["x"]
            ),
            201,
        )

        _, own_meta = validate_paginated(
            api.list_payments(books["nx"], books["x"], {"limit": 50})
        )
        assert own_meta["total_count"] == 1

        _, other_meta = validate_paginated(
            api.list_verifications(books["py"], COMPLIANCE, {"limit": 50})
        )
        assert other_meta["total_count"] == 0, "note NY was never attested by anyone"


class TestSegregationOfDutiesComparesIdentitiesNotRoles:
    """Both two-person controls are keyed on `X-User-ID`, so every violation here
    is staged with the correct role and only the identity colliding."""

    def _priced(self, api):
        """Note A, DRAFT, originated under the handle `analyst-origin`."""
        ctx = fixtures.origination_context(
            api,
            insured_payload=factories.insured(
                legal_name="Cascade Logistics Inc", email="ap@cascade.example"
            ),
        )
        return fixtures.draft_agreement(
            api,
            ctx,
            policies=[
                factories.financed_policy(
                    ctx["insurer_id"], policy_number="MC-SD-A"
                )
            ],
        )

    def _noticed(self, api):
        """Note B, activated on the canonical 600000 policy, swept delinquent on
        2026-10-12 and noticed the same day by `analyst-notice`."""
        return fixtures.noticed_note(api, policy_number="MC-SD-B")

    def _at_the_boundary(self, api):
        """The same note B with the clock standing on the effective cancel date."""
        bundle = self._noticed(api)
        fixtures.set_clock(api, "2026-10-22T00:00:00Z")
        return bundle

    def _issuer_paid(self, api):
        """A 1000-cent payment taken by the notice issuer on the boundary day."""
        bundle = self._at_the_boundary(api)
        bundle["payment"] = validate_success(
            api.create_payment(
                bundle["agreement_id"],
                factories.payment(1000, "2026-10-22"),
                ANALYST_NOTICE,
            ),
            201,
        )
        return bundle

    def test_the_originating_analyst_is_frozen_onto_the_note(self, api):
        """The handle that opened the note is kept for the later control.

        The PRD states: "its `originated_by_user_id` is frozen from `X-User-ID` for
        the later two-person control".

        Design: Corner/rbac/segregation_of_duties_same_user_cannot_price_and_approve_or_notice_and_execute
        """
        bundle = self._priced(api)

        assert bundle["agreement"]["originated_by_user_id"] == "analyst-origin"
        assert bundle["agreement"]["status"] == "DRAFT"
        assert bundle["agreement"]["rate_exception_approved"] is False

    def test_the_originating_handle_cannot_approve_its_own_pricing(self, api):
        """A ComplianceOfficer whose `X-User-ID` is the originator is refused.

        The PRD states: "The approver may not be the analyst recorded in
        `originated_by_user_id`; that comparison is the two-person control on pricing
        and yields `ERR_SOD_ORIGINATOR_CANNOT_APPROVE`."

        Design: Corner/rbac/segregation_of_duties_same_user_cannot_price_and_approve_or_notice_and_execute
        """
        bundle = self._priced(api)

        validate_error(
            api.approve_rate_exception(
                bundle["agreement_id"],
                factories.rate_exception(
                    override_annual_rate_bps=1800,
                    justification="approved by the very user who priced the note",
                ),
                make_compliance_headers("analyst-origin"),
            ),
            ApiErrorId.SOD_ORIGINATOR_CANNOT_APPROVE,
            403,
        )

        note = fixtures.read_agreement(api, bundle["agreement_id"])
        assert note["rate_exception_approved"] is False, (
            "the refused approval left nothing behind"
        )
        assert note["approved_annual_rate_bps"] is None
        assert note["rate_exception_approved_by_user_id"] is None
        assert note["version"] == 2, "creation and the policy attachment, nothing else"

    def test_an_independent_officer_is_accepted_on_the_identical_payload(self, api):
        """Only the identity was wrong, so a second pair of eyes settles it.

        The PRD states: "It sets `rate_exception_approved` to true, records the
        approver as `rate_exception_approved_by_user_id`, copies
        `override_service_fee_cents` into `approved_service_fee_cap_cents` and
        `override_annual_rate_bps` into `approved_annual_rate_bps` when each is
        supplied, and advances the note's `version`."

        Design: Corner/rbac/segregation_of_duties_same_user_cannot_price_and_approve_or_notice_and_execute
        """
        bundle = self._priced(api)
        payload = factories.rate_exception(
            override_annual_rate_bps=1800,
            justification="independent second pair of eyes on the pricing exception",
        )

        validate_error(
            api.approve_rate_exception(
                bundle["agreement_id"], payload, make_compliance_headers("analyst-origin")
            ),
            ApiErrorId.SOD_ORIGINATOR_CANNOT_APPROVE,
            403,
        )
        granted = validate_success(
            api.approve_rate_exception(
                bundle["agreement_id"], payload, COMPLIANCE_APPROVER
            ),
            200,
        )

        assert granted["rate_exception_approved"] is True
        assert granted["rate_exception_approved_by_user_id"] == "compliance-approver"
        assert granted["approved_annual_rate_bps"] == 1800
        assert granted["version"] == 3, "the approval is the third mutation of the note"

    def test_the_pricing_control_is_not_a_blanket_same_user_ban(self, api):
        """The originator may still submit the note it opened.

        The PRD states: "Submitting the draft advances the financing status `DRAFT`
        → `PENDING_VERIFICATION` and prices the note provisionally."

        Design: Corner/rbac/segregation_of_duties_same_user_cannot_price_and_approve_or_notice_and_execute
        """
        bundle = self._priced(api)
        validate_success(
            api.approve_rate_exception(
                bundle["agreement_id"],
                factories.rate_exception(
                    override_annual_rate_bps=1800,
                    justification="independent second pair of eyes on the pricing exception",
                ),
                COMPLIANCE_APPROVER,
            ),
            200,
        )

        submitted = validate_success(
            api.submit_agreement(bundle["agreement_id"], ANALYST_ORIGIN), 200
        )

        assert submitted["status"] == "PENDING_VERIFICATION", (
            "segregation binds the pricing approval, not origination itself"
        )
        assert submitted["originated_by_user_id"] == "analyst-origin"

    def test_the_sweep_carries_the_second_note_into_delinquency(self, api):
        """One note advanced to LATE and one fee assessed on the missed
        installment.

        The PRD states: "When all conditions hold, the fee amount is computed by
        taking the installment's `amount_cents` multiplied by the regime's
        `late_fee_bps`, divided by 10000 and rounded half up, and then clamping that
        raw figure into the statutory band — first raising it to `late_fee_min_cents`
        if it falls below the floor, then lowering it to `late_fee_max_cents` if it
        exceeds the ceiling." and "An agreement that acquires a newly past-due
        installment while `CURRENT` advances `CURRENT` → `LATE` in the same pass."

        Design: Corner/rbac/segregation_of_duties_same_user_cannot_price_and_approve_or_notice_and_execute
        """
        bundle = self._noticed(api)

        assert bundle["activated"]["total_of_payments_cents"] == 539650
        assert bundle["servicing_run"]["agreements_advanced_to_late"] == 1
        assert bundle["servicing_run"]["late_fees_assessed"] == 1
        assert bundle["late_fee_amount_cents"] == late_fee_cents(89941, 500, 500, 10000)
        assert bundle["late_fee_amount_cents"] == 4497

    def test_the_notice_records_the_analyst_who_issued_it(self, api):
        """The issuing handle, the statutory date and the frozen arrears.

        The PRD states: "A successful issuance writes a notice in `ISSUED` status
        with `issued_date` set to the clock date, `issued_by_user_id` taken from
        `X-User-ID`, `notice_days` snapshotted from the regime's `noic_notice_days`
        at that moment, and `effective_cancel_date` set to `issued_date` advanced by
        `notice_days` calendar days."

        Design: Corner/rbac/segregation_of_duties_same_user_cannot_price_and_approve_or_notice_and_execute
        """
        bundle = self._noticed(api)
        notice = bundle["notice"]

        assert notice["issued_by_user_id"] == "analyst-notice"
        assert notice["issued_date"] == "2026-10-12"
        assert notice["notice_days"] == 10
        assert notice["effective_cancel_date"] == "2026-10-22"
        assert notice["past_due_amount_cents"] == 89941 + 4497 == 94438
        assert notice["status"] == "ISSUED"

    def test_the_notice_issuer_cannot_exercise_the_power_it_created(self, api):
        """On the boundary day, with the stage correct, the only defect left is the
        identity.

        The PRD states: "It requires an `ACTIVE` note whose `delinquency_stage` is
        `NOIC_ISSUED` and a notice in `ISSUED` status; the clock date must be on or
        after that notice's `effective_cancel_date`, or the attempt is refused with
        `ERR_NOTICE_PERIOD_NOT_ELAPSED` (HTTP 422), with the boundary day itself
        permitted; the acting `X-User-ID` must differ from the notice's
        `issued_by_user_id`, or the attempt is refused with
        `ERR_SOD_NOTICE_ISSUER_CANNOT_EXECUTE`".

        Design: Corner/rbac/segregation_of_duties_same_user_cannot_price_and_approve_or_notice_and_execute
        """
        bundle = self._at_the_boundary(api)

        validate_error(
            api.execute_cancellation(bundle["agreement_id"], ANALYST_NOTICE),
            ApiErrorId.SOD_NOTICE_ISSUER_CANNOT_EXECUTE,
            403,
        )

    def test_the_refused_execution_is_completely_inert(self, api):
        """Nothing was cancelled, nothing was requested, nothing was rebated.

        The PRD states: "All three are terminal: a `CURED`, `EXECUTED` or
        `SUPERSEDED` notice can never be executed, and an attempt is refused with
        `ERR_NOTICE_STATE_INVALID` (HTTP 409)."

        Design: Corner/rbac/segregation_of_duties_same_user_cannot_price_and_approve_or_notice_and_execute
        """
        bundle = self._at_the_boundary(api)
        before = fixtures.read_agreement(api, bundle["agreement_id"])

        validate_error(
            api.execute_cancellation(bundle["agreement_id"], ANALYST_NOTICE),
            ApiErrorId.SOD_NOTICE_ISSUER_CANNOT_EXECUTE,
            403,
        )

        notices = fixtures.read_notices(api, bundle["agreement_id"])
        assert len(notices) == 1
        assert notices[0]["status"] == "ISSUED", (
            "neither EXECUTED nor SUPERSEDED: the notice is still live"
        )
        after = fixtures.read_agreement(api, bundle["agreement_id"])
        assert after["version"] == before["version"]
        assert after["delinquency_stage"] == "NOIC_ISSUED"
        assert after["unpaid_finance_charge_cents"] == 37650, "no rebate was granted"
        assert fixtures.read_policy(api, bundle["policy_id"])["status"] == "VERIFIED"
        _, meta = validate_paginated(
            api.list_carrier_cancellation_requests(
                COMPLIANCE, {"agreement_id": bundle["agreement_id"], "limit": 50}
            )
        )
        assert meta["total_count"] == 0

    def test_the_notice_issuer_may_still_take_the_borrowers_money(self, api):
        """The control is narrow: the issuer is not barred from the account.

        The PRD states: "Bucket one settles `OUTSTANDING` late fees, ordered by
        `assessed_date` ascending, then `installment_number` ascending, then
        `created_at` ascending; a fee is settled only if the unallocated remainder
        covers its `amount_cents` whole, and a remainder smaller than the fee leaves
        that fee `OUTSTANDING` and flows on rather than part-paying it." and "Bucket
        two pays `PAST_DUE` installments, ordered by `due_date` ascending then
        `installment_number` ascending, and inside a single installment the
        `finance_charge_component_cents` is retired before the
        `principal_component_cents`; partial application is allowed here and leaves
        the installment `PAST_DUE`."

        Design: Corner/rbac/segregation_of_duties_same_user_cannot_price_and_approve_or_notice_and_execute
        """
        bundle = self._issuer_paid(api)
        payment = bundle["payment"]

        assert payment["status"] == "POSTED"
        assert payment["applied_late_fee_cents"] == 0, (
            "1000 does not cover the 4497 fee whole, so it flows on"
        )
        assert payment["applied_finance_charge_cents"] == 1000
        assert payment["applied_principal_cents"] == 0
        assert payment["applied_unapplied_cents"] == 0

        note = fixtures.read_agreement(api, bundle["agreement_id"])
        assert note["late_fee_balance_cents"] == 4497
        assert note["unpaid_finance_charge_cents"] == 36650
        assert note["principal_balance_cents"] == 502000
        first = next(
            row
            for row in fixtures.read_installments(api, bundle["agreement_id"])
            if row["installment_number"] == 1
        )
        assert first["status"] == "PAST_DUE"
        assert first["paid_cents"] == 1000

    def test_a_second_analyst_completes_the_cancellation(self, api):
        """A different handle exercises the power, and the rebate cap bites.

        The PRD states: "Whichever method applies, the rebate is finally capped at
        the note's `unpaid_finance_charge_cents`, so a rebate can never create
        finance charge that was never owed." and "The operation reports
        `requests_created`, the aggregate `estimated_unearned_premium_cents`, the
        `rebate_applied_cents` it granted, and the `gross_balance_cents` of the note
        — its `principal_balance_cents` plus its post-rebate
        `unpaid_finance_charge_cents`."

        Design: Corner/rbac/segregation_of_duties_same_user_cannot_price_and_approve_or_notice_and_execute
        """
        bundle = self._issuer_paid(api)

        execution = validate_success(
            api.execute_cancellation(bundle["agreement_id"], ANALYST_EXECUTE), 200
        )

        assert execution["requests_created"] == 1
        assert execution["estimated_unearned_premium_cents"] == 516164
        assert rule_of_78_rebate_cents(37650, 6, 6) == 37650, (
            "no installment ever reached PAID, so the quotient is the whole charge"
        )
        assert execution["rebate_applied_cents"] == 36650, (
            "the quotient is capped at the unpaid finance charge the 1000-cent "
            "payment had already reduced"
        )
        assert execution["gross_balance_cents"] == 502000, (
            "principal plus the post-rebate finance charge, which is now zero"
        )

    def test_the_two_dimensions_moved_independently(self, api):
        """The collection dimension advanced; the financing dimension did not.

        The PRD states: "The execution then does six things at once." and "The
        `delinquency_stage` advances `NOIC_ISSUED` → `CANCELLATION_REQUESTED`, and
        the note's `version` advances."

        Design: Corner/rbac/segregation_of_duties_same_user_cannot_price_and_approve_or_notice_and_execute
        """
        bundle = self._issuer_paid(api)
        before = fixtures.read_agreement(api, bundle["agreement_id"])

        validate_success(
            api.execute_cancellation(bundle["agreement_id"], ANALYST_EXECUTE), 200
        )

        note = fixtures.read_agreement(api, bundle["agreement_id"])
        assert note["delinquency_stage"] == "CANCELLATION_REQUESTED"
        assert note["status"] == "ACTIVE", (
            "none of the six side effects touches the financing status"
        )
        assert note["version"] == before["version"] + 1
        notices = fixtures.read_notices(api, bundle["agreement_id"])
        assert notices[0]["status"] == "EXECUTED"
        assert notices[0]["executed_date"] == "2026-10-22"
