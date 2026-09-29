"""Who may act, on whose records, and what an unresolvable identifier returns.

Authentication is answered before anything else, then role membership, then the two
identity-backed scopes: a buyer's representative acts as a customer and a barge
master acts as a delivery asset. Segregation of duties then constrains even a
correctly-roled operator. Behind all of it sits one existence check per resource,
each with its own error id.
"""

import pytest

from test_helpers import (
    ApiErrorId,
    COMPLIANCE,
    COMPLIANCE_USER_ID,
    CREDIT,
    LAB,
    NON_EXISTENT_UUID,
    OPS,
    OPS_USER_ID,
    SURVEYOR,
    add_customer,
    add_second_asset,
    api_client,
    assert_credit_exposure,
    build_cleared_order,
    build_delivered_order,
    build_draft_nomination,
    build_reference_data,
    compliance_review_payload,
    create_bdn_payload,
    create_nomination_payload,
    make_barge_master_headers,
    make_customer_rep_headers,
    make_headers,
    make_ops_coordinator_headers,
    read_asset,
    read_nomination,
    read_order,
    validate_error,
    validate_paginated,
    validate_success,
)

NO_HEADERS = {}
UNKNOWN_ROLE_HEADERS = make_headers("hm-001", "HarbourMaster")

SECOND_BARGE = {"name": "Bunker Beta", "capacity_mt": 2500.000}
SECOND_BUYER = {"name": "Baltic Carriers"}

RETENTION_UNTIL = "2026-11-08T14:30:00"

NOT_FOUND_PROBES = [
    ("get_port", "OPS", ApiErrorId.ERR_PORT_NOT_FOUND),
    ("get_fuel_grade", "OPS", ApiErrorId.ERR_FUEL_GRADE_NOT_FOUND),
    ("get_customer", "CREDIT", ApiErrorId.ERR_CUSTOMER_NOT_FOUND),
    ("get_delivery_asset", "OPS", ApiErrorId.ERR_ASSET_NOT_FOUND),
    ("get_nomination", "OPS", ApiErrorId.ERR_NOMINATION_NOT_FOUND),
    ("get_delivery_order", "OPS", ApiErrorId.ERR_DELIVERY_ORDER_NOT_FOUND),
    ("get_bunker_delivery_note", "OPS", ApiErrorId.ERR_BDN_NOT_FOUND),
    ("get_quality_claim", "SURVEYOR", ApiErrorId.ERR_CLAIM_NOT_FOUND),
    ("get_lab_analysis", "LAB", ApiErrorId.ERR_LAB_ANALYSIS_NOT_FOUND),
    ("get_invoice", "CREDIT", ApiErrorId.ERR_INVOICE_NOT_FOUND),
    ("get_spill_incident", "COMPLIANCE", ApiErrorId.ERR_SPILL_INCIDENT_NOT_FOUND),
]

PROBE_HEADERS = {
    "OPS": OPS,
    "CREDIT": CREDIT,
    "SURVEYOR": SURVEYOR,
    "LAB": LAB,
    "COMPLIANCE": COMPLIANCE,
}


class TestAuthenticationIsAnsweredFirst:
    """Two header shapes fail authentication, and they fail it before anything else."""

    def test_absent_and_unknown_roles_are_rejected_before_the_payload_is_read(self):
        """PRD §2.1: "Every request to the API must carry two mandatory HTTP headers:
        `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the
        operational capacity in which they act. If either header is absent, or if
        `X-User-Role` is not one of the role names defined below, the request is rejected
        with `ERR_UNAUTHENTICATED` (HTTP 401)."
        PRD §2.1: "The system recognises exactly seven roles: `OpsCoordinator`,
        `ComplianceOfficer`, `Surveyor`, `CreditController`, `LabTechnician`,
        `CustomerRep`, and `BargeMaster`."
        PRD §2.8: "1. Header authentication — `ERR_UNAUTHENTICATED`."
        PRD §2.8: "6. Payload shape: required fields present, declared types respected,
        enum members valid, declared decimal scales respected, quantities strictly positive
        where declared so, and pagination parameters in range — `ERR_INVALID_REQUEST`."

        `HarbourMaster` is a plausible maritime title and a syntactically fine header
        value, but it is not one of the seven roles. The third probe carries no headers
        and an empty body at once, and must still answer on the headers.

        Design: Corner/rbac/missing_or_unknown_role_header_returns_401
        """
        ctx = build_reference_data(quotes=[])

        anonymous = api_client.get_port(ctx["port"]["id"], NO_HEADERS)
        validate_error(anonymous, ApiErrorId.ERR_UNAUTHENTICATED)

        unknown_role = api_client.get_port(ctx["port"]["id"], UNKNOWN_ROLE_HEADERS)
        validate_error(unknown_role, ApiErrorId.ERR_UNAUTHENTICATED)

        anonymous_write = api_client.create_port({}, NO_HEADERS)

        validate_error(anonymous_write, ApiErrorId.ERR_UNAUTHENTICATED)
        _, meta = validate_paginated(api_client.list_ports(OPS))
        assert meta["total_count"] == 1, (
            "Only the port from the setup may exist, got "
            f"{meta['total_count']} ports"
        )


class TestRolePermissionsAreNotSymmetric:
    """Two adjacent desks, two exclusive operations, neither borrowable."""

    def test_neither_desk_can_perform_the_others_exclusive_step(self):
        """PRD §2.1: "If the headers are valid but the declared role is not authorised
        for the requested operation, the request is rejected with
        `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."
        PRD §2.1: "The bunker operations desk acts as `OpsCoordinator`: it maintains
        reference data, takes in nominations, confirms stems, schedules barges and trucks,
        records port clearance, cancels orders, issues bunker delivery notes and releases
        retained samples. The regulatory desk acts as `ComplianceOfficer`:
        emission-control sulfur and documentation review, spill containment sign-off,
        incident closure and release of quarantined assets."
        PRD §3.3: "On intake the nomination's two dimensions are initialised
        independently: `fulfillment_status` to `DRAFT` and `compliance_status` to
        `PENDING_REVIEW`, with `compliance_reviewer_user_id` null."
        PRD §3.3: "A successful approval records the reviewing officer's `X-User-ID` as
        `compliance_reviewer_user_id` and increments the nomination's `version` by one."

        The desk that raised the stem cannot also clear it, which is what keeps the
        reviewer identity out of the intake role's hands; and the reviewing desk cannot
        reach across into confirmation either.

        Design: Corner/rbac/ops_coordinator_cannot_perform_compliance_review
        """
        ctx = build_draft_nomination(quotes=[])
        stem = ctx["nomination"]

        self_review = api_client.compliance_review(
            stem["id"], compliance_review_payload("APPROVE"), OPS
        )

        validate_error(self_review, ApiErrorId.ERR_ROLE_NOT_PERMITTED)
        after = read_nomination(ctx)
        assert after["compliance_status"] == "PENDING_REVIEW", (
            "The refused review must leave the stem pending, got "
            f"{after['compliance_status']}"
        )
        assert after["compliance_reviewer_user_id"] is None, (
            "No reviewer identity may be stamped, got "
            f"{after['compliance_reviewer_user_id']}"
        )
        assert after["version"] == stem["version"], (
            f"A refused review must not move the version, expected "
            f"{stem['version']}, got {after['version']}"
        )

        borrowed_confirm = api_client.confirm_nomination(stem["id"], COMPLIANCE)

        validate_error(borrowed_confirm, ApiErrorId.ERR_ROLE_NOT_PERMITTED)
        assert read_nomination(ctx)["fulfillment_status"] == "DRAFT", (
            "The refused confirmation must leave the stem in DRAFT, got "
            f"{read_nomination(ctx)['fulfillment_status']}"
        )


class TestCustomerScopeIsEnforcedByIdentity:
    """The representative's header id is the customer id, so scope is ownership."""

    def test_a_rep_reads_its_own_exposure_and_nothing_else(self):
        """PRD §2.1: "When `X-User-Role` is `CustomerRep`, `X-User-ID` is the `id` of the
        acting `Customer`; ownership checks on any resource that references a `Customer`
        compare the resource's customer foreign-key field to `X-User-ID`, and a mismatch
        is rejected with `ERR_CUSTOMER_SCOPE_VIOLATION` (HTTP 403)."
        PRD §2.1: "Concretely, that scope check guards six operations: raising a quality
        claim, requesting a retest on a claim, submitting a quantity decision on a delivery
        order, reading a customer's credit exposure, listing nominations, and listing
        quality claims."
        PRD §3.2: "`available_credit_usd` is the customer's `credit_limit_usd` minus that
        conservative exposure, rounded to two decimal places, and is permitted to be
        negative."

        Neither buyer has an invoice or a stem, so the owning read returns the zeroed
        projection against the full limit. The foreign buyer's projection is a 403 rather
        than a 404, and the customer read the exposure hangs off is closed to the
        representative entirely even for its own record.

        Design: Corner/rbac/customer_rep_cannot_read_another_customers_exposure
        """
        buyer_a = add_customer()
        buyer_b = add_customer(**SECOND_BUYER)
        rep_a = make_customer_rep_headers(buyer_a["id"])

        foreign = api_client.get_credit_exposure(buyer_b["id"], rep_a)
        validate_error(foreign, ApiErrorId.ERR_CUSTOMER_SCOPE_VIOLATION)

        own = validate_success(api_client.get_credit_exposure(buyer_a["id"], rep_a))

        assert_credit_exposure(own)
        assert own["outstanding_balance_usd"] == pytest.approx(0.00, abs=0.01), (
            f"Nothing is invoiced, got {own['outstanding_balance_usd']}"
        )
        assert own["conservative_exposure_usd"] == pytest.approx(0.00, abs=0.01), (
            f"Nothing is committed, got {own['conservative_exposure_usd']}"
        )
        assert own["open_commitment_count"] == 0, (
            f"There is no stem to commit, got {own['open_commitment_count']}"
        )
        assert own["available_credit_usd"] == pytest.approx(5000000.00, abs=0.01), (
            "The whole limit is available, got "
            f"{own['available_credit_usd']}"
        )
        assert own["credit_status"] == "OK", (
            f"Zero utilisation is OK, got {own['credit_status']}"
        )

        own_customer_record = api_client.get_customer(
            buyer_b["id"], make_customer_rep_headers(buyer_b["id"])
        )

        validate_error(own_customer_record, ApiErrorId.ERR_ROLE_NOT_PERMITTED)


class TestBargeMasterActsOnlyOnItsOwnAsset:
    """The master's header id is the asset id, so assignment is ownership."""

    def test_a_master_of_another_barge_cannot_start_this_transfer(self):
        """PRD §2.1: "When `X-User-Role` is `BargeMaster`, `X-User-ID` is the `id` of the
        acting `DeliveryAsset`; a `BargeMaster` may only act on a delivery order whose
        `asset_id` equals `X-User-ID`, and a mismatch is rejected with
        `ERR_ASSET_NOT_ASSIGNED` (HTTP 403). That check guards three operations: starting
        pumping, completing pumping, and reporting a spill incident."
        PRD §3.5: "A successful start writes the nomination's grade onto the asset as its
        `last_grade_id`, which is what makes the segregation rule bite on the asset's next
        stem."
        PRD §2.8: "5. Asset assignment for a `BargeMaster` — `ERR_ASSET_NOT_ASSIGNED`."

        The second barge is idle and has no order at all, so its master has no business
        starting this one; and the refusal must not write the grade onto either barge.

        Design: Corner/rbac/barge_master_cannot_pump_an_unassigned_asset
        """
        ctx = build_cleared_order()
        idle = add_second_asset(ctx, **SECOND_BARGE)

        wrong_master = api_client.start_pumping(
            ctx["order"]["id"], make_barge_master_headers(idle["id"])
        )

        validate_error(wrong_master, ApiErrorId.ERR_ASSET_NOT_ASSIGNED)
        assert read_order(ctx)["logistics_status"] == "CLEARED", (
            "The refused start must leave the order cleared, got "
            f"{read_order(ctx)['logistics_status']}"
        )
        assert read_asset(ctx)["last_grade_id"] is None, (
            "No grade may be written by a refused start, got "
            f"{read_asset(ctx)['last_grade_id']}"
        )

        started = validate_success(
            api_client.start_pumping(
                ctx["order"]["id"], make_barge_master_headers(ctx["asset"]["id"])
            )
        )

        assert started["logistics_status"] == "PUMPING", (
            f"The assigned master must be able to start, got "
            f"{started['logistics_status']}"
        )
        assert read_asset(ctx)["last_grade_id"] == ctx["grade"]["id"], (
            "The successful start writes the grade onto the acting barge, got "
            f"{read_asset(ctx)['last_grade_id']}"
        )
        assert read_asset(ctx, asset_id=idle["id"])["last_grade_id"] is None, (
            "The idle barge must be untouched, got "
            f"{read_asset(ctx, asset_id=idle['id'])['last_grade_id']}"
        )


class TestSegregationOfDutiesOnTheNote:
    """A correctly-roled operator can still be the wrong person."""

    def test_the_compliance_reviewer_cannot_issue_the_note_for_that_stem(self):
        """PRD §2.1: "Two pairings are policed: the `OpsCoordinator` whose `X-User-ID` is
        recorded as `issued_by_user_id` on a bunker delivery note must differ from the
        `compliance_reviewer_user_id` recorded on the nomination behind that note, and the
        `CreditController` who books a remediation credit must have an `X-User-ID`
        differing from the `proposed_by_user_id` recorded when the remediation was
        proposed."
        PRD §3.7: "The segregation-of-duties rule of §2.1 also applies here: the issuing
        coordinator's `X-User-ID` is stored as `issued_by_user_id` and must differ from the
        `compliance_reviewer_user_id` on the nomination behind the order."
        PRD §3.7: "A newly issued note snapshots `delivered_quantity_mt` from the order's
        `agreed_quantity_mt` at the moment of issuance, sets `status` to `ISSUED`, and
        starts the sample custody clock: `sample_retention_until` is the note's
        `created_at` plus a 90-day retention period, `sample_custody_status` begins as
        `RETAINED`, and `sample_released_at` is null."

        The reviewer's identifier is a valid operations identifier — the role check
        passes and only the pairing fails. The note number and seal it tried to use must
        remain free for the colleague who legitimately issues the note.

        Design: Corner/rbac/compliance_reviewer_cannot_also_issue_the_bdn
        """
        ctx = build_delivered_order()
        assert ctx["nomination"]["compliance_reviewer_user_id"] == COMPLIANCE_USER_ID, (
            "The setup must have recorded the reviewer, got "
            f"{ctx['nomination']['compliance_reviewer_user_id']}"
        )
        payload = create_bdn_payload(ctx["order"]["id"])

        self_issued = api_client.create_bunker_delivery_note(
            payload, make_ops_coordinator_headers(COMPLIANCE_USER_ID)
        )

        validate_error(self_issued, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
        _, meta = validate_paginated(
            api_client.list_bunker_delivery_notes(
                OPS, params={"delivery_order_id": ctx["order"]["id"]}
            )
        )
        assert meta["total_count"] == 0, (
            f"The refused note must not exist, got {meta['total_count']} notes"
        )

        note = validate_success(
            api_client.create_bunker_delivery_note(payload, OPS), 201
        )

        assert note["issued_by_user_id"] == OPS_USER_ID, (
            f"The issuing identity must be recorded, got {note['issued_by_user_id']}"
        )
        assert note["bdn_number"] == payload["bdn_number"], (
            "The refused attempt must not have consumed the note number, got "
            f"{note['bdn_number']}"
        )
        assert note["sample_seal_number"] == payload["sample_seal_number"], (
            "The refused attempt must not have consumed the seal number, got "
            f"{note['sample_seal_number']}"
        )
        assert note["status"] == "ISSUED", (
            f"The note opens ISSUED, got {note['status']}"
        )
        assert note["sample_custody_status"] == "RETAINED", (
            f"The sample starts retained, got {note['sample_custody_status']}"
        )
        assert note["sample_retention_until"].startswith(RETENTION_UNTIL), (
            "90 days after 2026-08-10T14:30:00Z is 2026-11-08T14:30:00Z, got "
            f"{note['sample_retention_until']}"
        )


class TestEveryResourceHasItsOwnExistenceError:
    """Eleven resources, eleven distinct not-found ids, and one precedence case."""

    @pytest.mark.parametrize(
        "reader, role, expected_error_id",
        NOT_FOUND_PROBES,
        ids=[probe[0] for probe in NOT_FOUND_PROBES],
    )
    def test_an_absent_identifier_names_the_resource_that_is_missing(
        self, reader, role, expected_error_id
    ):
        """PRD §2.7: "The order of resolution across the system is: `port_id`, then
        `grade_id`, then `customer_id`, then `asset_id`, then `nomination_id`, then
        `delivery_order_id`, then `bdn_id`, then `claim_id`, then `retest_of_analysis_id`,
        then an invoice `id`, then a spill incident `id`. The corresponding rejections are
        `ERR_PORT_NOT_FOUND`, `ERR_FUEL_GRADE_NOT_FOUND`, `ERR_CUSTOMER_NOT_FOUND`,
        `ERR_ASSET_NOT_FOUND`, `ERR_NOMINATION_NOT_FOUND`,
        `ERR_DELIVERY_ORDER_NOT_FOUND`, `ERR_BDN_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`,
        `ERR_LAB_ANALYSIS_NOT_FOUND`, `ERR_INVOICE_NOT_FOUND` and
        `ERR_SPILL_INCIDENT_NOT_FOUND`, each carrying HTTP 404."
        PRD §2.2: "The `error_id` is a unique, machine-readable string that identifies
        the specific error."

        The database is empty, so every one of the eleven reads addresses a record that
        cannot exist, and each must name its own resource rather than a generic
        not-found.

        Design: Corner/errors/every_existence_error_id_returns_not_found
        """
        response = getattr(api_client, reader)(
            NON_EXISTENT_UUID, PROBE_HEADERS[role]
        )

        validate_error(response, expected_error_id)

    def test_the_leftmost_unresolvable_reference_outranks_the_body_rules(self):
        """PRD §2.7: "Requests that name several records — in the path, in the body, or
        both — are validated for existence in a fixed left-to-right, outer-to-inner order,
        and the first identifier that fails to resolve determines the error returned."
        PRD §2.7: "A nomination intake naming a non-existent port and a non-existent
        grade in the same payload therefore reports the port failure, never the grade
        failure."
        PRD §2.8: "3. Existence of every referenced record, in the order given in §2.7 —
        the various not-found rejections."

        The intake names three absent records and carries a negative tonnage as well.
        Existence is answered before the payload rules and the port comes first in the
        resolution order, so only the port failure may be reported.

        Design: Corner/errors/every_existence_error_id_returns_not_found
        """
        payload = create_nomination_payload(
            NON_EXISTENT_UUID,
            NON_EXISTENT_UUID,
            NON_EXISTENT_UUID,
            nominated_quantity_mt=-5.000,
        )

        response = api_client.create_nomination(payload, OPS)

        validate_error(response, ApiErrorId.ERR_PORT_NOT_FOUND)
        _, meta = validate_paginated(api_client.list_nominations(OPS))
        assert meta["total_count"] == 0, (
            f"No nomination may have been created, got {meta['total_count']}"
        )
