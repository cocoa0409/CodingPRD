"""Role authority, the two version guards, the flag default and the immediacy of a write."""

from test_helpers import (
    API_PREFIX,
    AUDIT_MANAGER_ID,
    AUDIT_SELECTION_THRESHOLD,
    LICENSING_OFFICER_ID,
    NON_EXISTENT_UUID,
    ROLE_TAX_SUPERVISOR,
    TAX_SUPERVISOR_ID,
    ApiErrorId,
    assert_assessment_money,
    assert_balance_matches_ledger,
    assert_bond_instrument,
    assert_bond_position,
    assert_case_dimensions,
    assert_cents,
    assert_gallons,
    assert_ledger_sequence,
    assert_return_money,
    assert_return_statuses,
    assert_starts_at,
    assert_total_count,
    build_user_headers,
    ids_of,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.factories import (
    amendment_payload,
    assessment_payload,
    audit_case_payload,
    bond_payload,
    cross_match_run_payload,
    inspection_payload,
    licensee_payload,
    payment_payload,
    return_payload,
    terminal_payload,
)


class TestOperatorRoleAuthority:
    def test_each_operator_role_drives_its_own_verb_on_one_shared_licensee(
        self,
        api,
        world,
        officer_headers,
        inspector_headers,
        manager_headers,
        supervisor_headers,
    ):
        """Four roles each work their own verb on one retailer without borrowing authority.

        PRD: "**`LicensingOfficer`** runs the licensing and bonding desk: it registers licensees
        and terminals, issues and revokes exemption certificates, posts and releases surety bonds,
        and drives the license through `PENDING_BOND`, `ACTIVE`, `SUSPENDED` and `REVOKED`."
        PRD: "`penalty_cents` is then computed in a strictly pinned order. A base amount is taken
        as the **greater** of a flat 100000 cents and `gallons_in_tank` multiplied by 1000 cents
        per gallon rounded half up. A multiplier is selected from the frozen count: 1.0 when it is
        0, 2.0 when it is exactly 1, and 3.0 for two or more."
        PRD: "A new case starts with `case_status` `OPEN`, `assessment_status` `NONE`,
        `response_rounds` 0, `additional_tax_cents` 0, `evasion_indicator` false,
        `assessed_by_user_id`, `protest_grounds` and `abatement_reason` null, and
        `opened_by_user_id` set to the acting `X-User-ID`."
        PRD: "Dismissal sets `status` to `DISMISSED`, appends a `PENALTY_REVERSAL` ledger entry
        for the negative of `penalty_cents` — a compensating entry, never a deletion or mutation
        of the original `PENALTY` row — and re-derives `balance_cents` back to exactly its
        pre-penalty value, which is what keeps Invariant M exact. The licensee's
        `dyed_violation_count` decreases by one."

        Design: Corner/rbac/each_operator_role_can_perform_its_own_exclusive_operations
        """
        retailer = validate_success(
            api.create_licensee(
                licensee_payload(
                    "RETAILER",
                    legal_name="Roles Retail Stops LLC",
                    fein="41-8400001",
                    retail_channel="HIGHWAY",
                ),
                officer_headers,
            ),
            expected_status=201,
        )
        terminal = validate_success(
            api.create_terminal(
                terminal_payload(
                    name="Roles River Terminal",
                    state_code="MN",
                    terminal_control_number="T84MN8400",
                ),
                officer_headers,
            ),
            expected_status=201,
        )
        assert terminal["terminal_control_number"] == "T84MN8400"

        inspection = validate_success(
            api.create_inspection(
                inspection_payload(
                    retailer["id"],
                    "POSITIVE",
                    40.00,
                    "2026-07-27",
                    vehicle_identifier="MN-TRK-8400",
                ),
                inspector_headers,
            ),
            expected_status=201,
        )
        assert inspection["status"] == "PENALTY_ASSESSED"
        assert inspection["prior_positive_count"] == 0
        assert_cents(inspection["penalty_cents"], 100000, "penalty_cents at the 100000 floor")

        case = validate_success(
            api.create_audit_case(
                audit_case_payload(
                    retailer["id"],
                    "2026-07",
                    "2026-07",
                    selection_method="ROADSIDE_REFERRAL",
                ),
                manager_headers,
            ),
            expected_status=201,
        )
        assert_case_dimensions(case, "OPEN", "NONE")
        assert case["opened_by_user_id"] == AUDIT_MANAGER_ID
        assert case["selection_score"] == 0

        advanced = validate_success(api.advance_case(case["id"], "FIELDWORK", manager_headers))
        assert_case_dimensions(advanced, "FIELDWORK", "NONE")

        dismissed = validate_success(
            api.dismiss_inspection(
                inspection["id"], "Sample chain of custody was broken", supervisor_headers
            )
        )
        assert dismissed["status"] == "DISMISSED"

        after = world.licensee(retailer["id"])
        assert after["dyed_violation_count"] == 0
        entries = world.ledger(retailer["id"])
        assert_ledger_sequence(entries, [("PENALTY", 100000), ("PENALTY_REVERSAL", -100000)])
        assert_cents(after["balance_cents"], 0, "balance_cents restored by the reversal")
        assert_balance_matches_ledger(after, entries)

    def test_no_role_may_reach_for_another_roles_exclusive_operation(
        self,
        api,
        world,
        officer_headers,
        examiner_headers,
        inspector_headers,
        manager_headers,
        supervisor_headers,
    ):
        """The 403 is decided from the role alone, against ids that all exist.

        PRD: "A syntactically valid request whose role is not authorized for the addressed
        operation is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
        PRD: "2. **Authorization** — the acting role appears in the endpoint's authorized set
        (`ERR_UNAUTHORIZED`)."
        PRD: "- **`FieldInspector`** performs roadside enforcement: it records dyed-fuel
        inspections in the field. It cannot dismiss its own findings and cannot touch returns,
        refunds or audits."
        PRD: "- **`AuditManager`** owns audit selection and casework: it opens cases by risk score
        or referral and drives the case dimension through fieldwork, findings, taxpayer response
        and closure. It deliberately has no money authority."

        Design: Corner/rbac/no_role_may_invoke_another_roles_exclusive_operation
        """
        distributor = validate_success(
            api.create_licensee(
                licensee_payload(
                    "DISTRIBUTOR",
                    legal_name="Denial Distribution Inc",
                    fein="41-8500001",
                ),
                officer_headers,
            ),
            expected_status=201,
        )
        case = validate_success(
            api.create_audit_case(
                audit_case_payload(
                    distributor["id"],
                    "2026-07",
                    "2026-07",
                    selection_method="ROADSIDE_REFERRAL",
                ),
                manager_headers,
            ),
            expected_status=201,
        )
        assert case["opened_by_user_id"] == AUDIT_MANAGER_ID

        validate_error(
            api.create_licensee(
                licensee_payload(
                    "RETAILER",
                    legal_name="Inspector Overreach LLC",
                    fein="41-8500002",
                ),
                inspector_headers,
            ),
            ApiErrorId.UNAUTHORIZED,
            expected_status=403,
        )
        _rows, meta = validate_paginated(api.list_licensees(officer_headers))
        assert_total_count(meta, 1, "licensees after the refused registration")

        validate_error(
            api.issue_assessment(
                case["id"], assessment_payload(250000, False), manager_headers
            ),
            ApiErrorId.UNAUTHORIZED,
            expected_status=403,
        )
        validate_error(
            api.create_payment(distributor["id"], payment_payload(100000), examiner_headers),
            ApiErrorId.UNAUTHORIZED,
            expected_status=403,
        )
        validate_error(
            api.create_audit_case(
                audit_case_payload(
                    distributor["id"],
                    "2026-09",
                    "2026-09",
                    selection_method="ROADSIDE_REFERRAL",
                ),
                supervisor_headers,
            ),
            ApiErrorId.UNAUTHORIZED,
            expected_status=403,
        )

        untouched = validate_success(api.get_audit_case(case["id"], manager_headers))
        assert_case_dimensions(untouched, "OPEN", "NONE")
        assert world.ledger(distributor["id"]) == []

    def test_the_two_shared_verbs_answer_to_both_of_their_holders(
        self, api, world, officer_headers, examiner_headers, supervisor_headers
    ):
        """Suspend and cross-match each have two holders, and the second call meets a state rule.

        PRD: "`PENDING_BOND → ACTIVE` and `SUSPENDED → ACTIVE` are both reinstatement legs driven
        by a `LicensingOfficer`; `ACTIVE → SUSPENDED` is a suspension leg driven by a
        `LicensingOfficer` or a `TaxSupervisor` and requires a `reason`; and `PENDING_BOND →
        REVOKED`, `ACTIVE → REVOKED` and `SUSPENDED → REVOKED` are all the same revocation leg,
        driven by a `LicensingOfficer` with a `reason`, ending in the terminal `REVOKED` state.
        Requesting a transition the current `status` does not admit — reinstating an already
        `ACTIVE` licensee, suspending one that is not `ACTIVE`, or touching one that is already
        `REVOKED` — fails with `ERR_LICENSEE_STATE_INVALID` (HTTP 409)."
        PRD: "A `ReturnsExaminer` or `TaxSupervisor` starts a run by naming a `period_month`,
        optionally overriding the default tolerance through `tolerance_gallons`."
        PRD: "And at most one run may exist per period, so a second run for the same
        `period_month` fails with `ERR_DUPLICATE_MATCH_RUN` (HTTP 409)."
        PRD: "Every cell examined increments `matched_cells_count`, whether or not it produces a
        finding."

        Design: Corner/rbac/suspend_and_cross_match_are_open_to_both_of_their_holders
        """
        first = world.active_licensee(
            "SUPPLIER", legal_name="Shared One Fuel Supply LLC", fein="41-8600001"
        )
        second = world.active_licensee(
            "SUPPLIER", legal_name="Shared Two Fuel Supply LLC", fein="41-8600002"
        )
        world.set_clock("2026-09-05T00:00:00Z")

        by_officer = validate_success(
            api.suspend_licensee(
                first["id"], "Bond surety withdrew its guarantee", officer_headers
            )
        )
        assert by_officer["status"] == "SUSPENDED"
        by_supervisor = validate_success(
            api.suspend_licensee(
                second["id"], "Repeated schedule irregularities", supervisor_headers
            )
        )
        assert by_supervisor["status"] == "SUSPENDED"

        run = validate_success(
            api.create_cross_match_run(cross_match_run_payload("2026-08"), examiner_headers),
            expected_status=201,
        )
        assert run["run_status"] == "COMPLETED"
        assert run["matched_cells_count"] == 0
        assert run["discrepancy_count"] == 0
        assert_gallons(run["tolerance_gallons"], 5.00, "the snapshotted default tolerance")

        validate_error(
            api.create_cross_match_run(cross_match_run_payload("2026-08"), supervisor_headers),
            ApiErrorId.DUPLICATE_MATCH_RUN,
            expected_status=409,
        )
        validate_error(
            api.suspend_licensee(first["id"], "A second look at the surety", supervisor_headers),
            ApiErrorId.LICENSEE_STATE_INVALID,
            expected_status=409,
        )


class TestLicenseeAgentScope:
    def test_an_agent_is_refused_by_id_and_silently_narrowed_on_a_list(
        self, api, world, officer_headers, examiner_headers
    ):
        """The scope rule has two shapes: 403 by id, and a narrowed 200 on a list.

        PRD: "When `X-User-Role` is `LicenseeAgent`, `X-User-ID` is the `id` of the acting
        `Licensee`; ownership checks on any resource that references a `Licensee` compare the
        resource's foreign-key field to `X-User-ID`."
        PRD: "Addressing a single resource owned by some other licensee fails with
        `ERR_LICENSEE_SCOPE_VIOLATION` (HTTP 403). List endpoints behave differently: rather than
        erroring, they are silently narrowed to rows belonging to the agent's own licensee."
        PRD: "3. **Licensee scope** — for a `LicenseeAgent`, `X-User-ID` owns the addressed
        resource (`ERR_LICENSEE_SCOPE_VIOLATION`). This runs *before* any state, business or
        fiscal check, so an agent poking at another licensee's resource never learns whether that
        resource was in a legal state."

        Design: Corner/rbac/licensee_agent_cannot_read_another_licensee_and_its_lists_are_narrowed
        """
        one = validate_success(
            api.create_licensee(
                licensee_payload(
                    "DISTRIBUTOR",
                    legal_name="Scope One Distribution Inc",
                    fein="41-8700001",
                ),
                officer_headers,
            ),
            expected_status=201,
        )
        two = validate_success(
            api.create_licensee(
                licensee_payload(
                    "DISTRIBUTOR",
                    legal_name="Scope Two Distribution Inc",
                    fein="41-8700002",
                ),
                officer_headers,
            ),
            expected_status=201,
        )
        world.set_clock("2026-09-05T00:00:00Z")
        mine = world.draft_return(one["id"], "2026-08")
        theirs = world.draft_return(two["id"], "2026-08")

        agent = world.agent(one["id"])
        validate_error(
            api.get_licensee(two["id"], agent),
            ApiErrorId.LICENSEE_SCOPE_VIOLATION,
            expected_status=403,
        )
        validate_error(
            api.get_return(theirs["id"], agent),
            ApiErrorId.LICENSEE_SCOPE_VIOLATION,
            expected_status=403,
        )

        rows, meta = validate_paginated(api.list_returns(agent))
        assert_total_count(meta, 1, "the returns an agent may see")
        assert ids_of(rows) == [mine["id"]]

        all_rows, all_meta = validate_paginated(api.list_returns(examiner_headers))
        assert_total_count(all_meta, 2, "the returns an examiner may see")
        assert sorted(ids_of(all_rows)) == sorted([mine["id"], theirs["id"]])

        validate_error(
            api.create_return(return_payload(two["id"], "2026-08"), agent),
            ApiErrorId.LICENSEE_SCOPE_VIOLATION,
            expected_status=403,
        )
        own = validate_success(api.get_licensee(one["id"], agent))
        assert own["id"] == one["id"]

    def test_a_request_with_no_identity_headers_is_unauthenticated_before_anything_else(
        self, api, officer_headers
    ):
        """Band 1 outranks the role check and the existence check alike.

        PRD: "Every request must carry two headers: `X-User-ID`, identifying the acting user, and
        `X-User-Role`, declaring the capacity in which that user acts. A request missing either
        header, carrying an empty `X-User-ID`, or naming a role outside the six recognized values
        is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."
        PRD: "1. **Authentication** — headers present and the role recognized
        (`ERR_UNAUTHENTICATED`)."
        PRD: "More generally, every request is evaluated against an ordered ladder of checks. The
        **first** check that fails produces the response, and no later check may override it."

        Design: Corner/rbac/requests_missing_auth_headers_are_unauthenticated
        """
        distributor = validate_success(
            api.create_licensee(
                licensee_payload(
                    "DISTRIBUTOR",
                    legal_name="Anonymous Distribution Inc",
                    fein="41-8800001",
                ),
                officer_headers,
            ),
            expected_status=201,
        )

        validate_error(
            api.raw("GET", f"{API_PREFIX}/licensees/{distributor['id']}", headers={}),
            ApiErrorId.UNAUTHENTICATED,
            expected_status=401,
        )
        readable = validate_success(api.get_licensee(distributor["id"], officer_headers))
        assert readable["legal_name"] == "Anonymous Distribution Inc"

        validate_error(
            api.raw("GET", f"{API_PREFIX}/licensees/{NON_EXISTENT_UUID}", headers={}),
            ApiErrorId.UNAUTHENTICATED,
            expected_status=401,
        )
        validate_error(
            api.raw(
                "POST",
                f"{API_PREFIX}/licensees",
                payload=licensee_payload(
                    "DISTRIBUTOR",
                    legal_name="Roleless Distribution Inc",
                    fein="41-8800002",
                ),
                headers={"X-User-ID": LICENSING_OFFICER_ID, "Content-Type": "application/json"},
            ),
            ApiErrorId.UNAUTHENTICATED,
            expected_status=401,
        )
        validate_error(
            api.raw(
                "GET",
                f"{API_PREFIX}/licensees/{distributor['id']}",
                headers={"X-User-ID": LICENSING_OFFICER_ID, "X-User-Role": "TaxCollector"},
            ),
            ApiErrorId.UNAUTHENTICATED,
            expected_status=401,
        )
        _rows, meta = validate_paginated(api.list_licensees(officer_headers))
        assert_total_count(meta, 1, "licensees after the unauthenticated create")


class TestAssessmentSegregation:
    def test_the_opener_may_not_assess_and_the_assessor_may_not_abate(
        self, api, world, officer_headers, manager_headers, supervisor_headers,
        supervisor_alt_headers,
    ):
        """Two identity bars on one case force three distinct users through open, assess, abate.

        PRD: "The acting `X-User-ID` must differ from `opened_by_user_id`: the manager who opened
        a case may not also assess it, and the attempt is refused with
        `ERR_ASSESSMENT_SEGREGATION_VIOLATION` (HTTP 422)."
        PRD: "Abatement also carries its own segregation rule: the acting `X-User-ID` must differ
        from `assessed_by_user_id`, and a supervisor abating its own assessment is refused with
        `ERR_ASSESSMENT_SEGREGATION_VIOLATION`."
        PRD: "For the five operator roles — `LicensingOfficer`, `ReturnsExaminer`,
        `TaxSupervisor`, `AuditManager` and `FieldInspector` — `X-User-ID` is an opaque operator
        identifier not tied to any persisted entity."
        PRD: "Issuance sets `assessment_status` to `ISSUED` and `assessed_by_user_id` to the
        acting `X-User-ID`, then appends an `ASSESSMENT` ledger entry for the positive
        `assessed_total_cents` naming the case as its source and re-derives the subject's
        `balance_cents`."
        PRD: "Abatement, available from `ISSUED` or `PROTESTED`, is the compensating counterpart
        of issuance. It takes an `abatement_reason`, sets `assessment_status` to `ABATED`, appends
        an `ABATEMENT` ledger entry for the negative of `assessed_total_cents` naming the case as
        its source, and re-derives `balance_cents` back to exactly its pre-assessment value — with
        both ledger rows retained, because the ledger is append-only."

        Design: Corner/rbac/the_case_opener_cannot_issue_its_own_assessment_and_the_assessor_cannot_abate_it
        """
        subject = validate_success(
            api.create_licensee(
                licensee_payload(
                    "DISTRIBUTOR",
                    legal_name="Duties Audit Distribution Inc",
                    fein="41-8900001",
                ),
                officer_headers,
            ),
            expected_status=201,
        )
        case = world.case_at(subject["id"], "PRELIM_FINDINGS", "2026-08", "2026-08")
        assert case["opened_by_user_id"] == AUDIT_MANAGER_ID
        world.set_clock("2026-09-25T00:00:00Z")

        opener_wearing_the_money_role = build_user_headers(AUDIT_MANAGER_ID, ROLE_TAX_SUPERVISOR)
        validate_error(
            api.issue_assessment(
                case["id"],
                assessment_payload(250000, False),
                opener_wearing_the_money_role,
            ),
            ApiErrorId.ASSESSMENT_SEGREGATION_VIOLATION,
            expected_status=422,
        )
        untouched = validate_success(api.get_audit_case(case["id"], manager_headers))
        assert_case_dimensions(untouched, "PRELIM_FINDINGS", "NONE")
        assert world.ledger(subject["id"]) == []

        issued = validate_success(
            api.issue_assessment(
                case["id"], assessment_payload(250000, False), supervisor_headers
            )
        )
        assert issued["assessed_by_user_id"] == TAX_SUPERVISOR_ID
        assert_case_dimensions(issued, "PRELIM_FINDINGS", "ISSUED")
        assert_assessment_money(issued, 250000, 25000, 250, 275250)

        validate_error(
            api.abate_assessment(case["id"], "Findings withdrawn on review", supervisor_headers),
            ApiErrorId.ASSESSMENT_SEGREGATION_VIOLATION,
            expected_status=422,
        )
        abated = validate_success(
            api.abate_assessment(
                case["id"], "Findings withdrawn on review", supervisor_alt_headers
            )
        )
        assert_case_dimensions(abated, "PRELIM_FINDINGS", "ABATED")
        entries = world.ledger(subject["id"])
        assert_ledger_sequence(entries, [("ASSESSMENT", 275250), ("ABATEMENT", -275250)])
        after = world.licensee(subject["id"])
        assert_cents(after["balance_cents"], 0, "balance_cents back to its pre-assessment value")
        assert_balance_matches_ledger(after, entries)


class TestOptimisticConcurrencyLayer:
    def test_a_bond_post_carrying_the_pre_activation_version_is_refused_and_creates_nothing(
        self, api, world, officer_headers
    ):
        """The guard protects a rider the stale client never saw, on a version an activate bumped.

        PRD: "Posting a surety bond for a licensee requires `expected_licensee_version`, carrying
        the client's last observed `version` of the target `Licensee`. If that value does not equal
        the licensee's current `version`, the request is rejected with
        `ERR_STALE_LICENSEE_VERSION` (HTTP 412) and no bond is created."
        PRD: "Posting is a create-with-supersede. The new instrument is created with `status`
        `ACTIVE` and `release_reason` null. Any *older* instrument of the same licensee that was
        still `ACTIVE` is moved to `RELEASED` with `release_reason` set to
        `SUPERSEDED_BY_NEW_BOND`, so that after the post the licensee's `posted_bond_cents` is
        exactly the new instrument's `amount_cents` and nothing more. The licensee's
        `posted_bond_cents` and `bond_deficiency_cents` are then re-derived and the licensee's
        `version` increments, alongside the `version` increments on the new and superseded
        instruments."
        PRD: "`bond_deficiency_cents` is the amount by which the requirement exceeds what is
        posted, floored at zero — when posted bond meets or exceeds the requirement, the deficiency
        is exactly 0."

        Design: Corner/cross-cutting complexity layers/a_second_bond_post_carrying_the_pre_activation_licensee_version_returns_412
        """
        supplier = validate_success(
            api.create_licensee(
                licensee_payload(
                    "SUPPLIER",
                    legal_name="Version Guard Fuel Supply LLC",
                    fein="41-9000001",
                ),
                officer_headers,
            ),
            expected_status=201,
        )
        first_seen_version = supplier["version"]
        assert_bond_position(supplier, 1500000, 0, 1500000, 500000)

        bond_a = validate_success(
            api.post_bond(
                supplier["id"],
                bond_payload(
                    1500000,
                    first_seen_version,
                    surety_name="Granite Surety Co",
                    effective_date="2026-07-01",
                ),
                officer_headers,
            ),
            expected_status=201,
        )
        activated = validate_success(api.activate_licensee(supplier["id"], officer_headers))
        assert activated["status"] == "ACTIVE"
        bond_b = validate_success(
            api.post_bond(
                supplier["id"],
                bond_payload(
                    2000000,
                    activated["version"],
                    surety_name="Basalt Indemnity Co",
                    effective_date="2026-07-15",
                ),
                officer_headers,
            ),
            expected_status=201,
        )

        validate_error(
            api.post_bond(
                supplier["id"],
                bond_payload(
                    900000,
                    first_seen_version,
                    surety_name="Stale View Surety Co",
                    effective_date="2026-07-20",
                ),
                officer_headers,
            ),
            ApiErrorId.STALE_LICENSEE_VERSION,
            expected_status=412,
        )

        rows, meta = validate_paginated(api.list_bonds(supplier["id"], officer_headers))
        assert_total_count(meta, 2, "bond instruments after the refused post")
        by_id = {row["id"]: row for row in rows}
        assert_bond_instrument(by_id[bond_a["id"]], "RELEASED", "SUPERSEDED_BY_NEW_BOND", 1500000)
        assert_bond_instrument(by_id[bond_b["id"]], "ACTIVE", None, 2000000)
        current = world.licensee(supplier["id"])
        assert current["status"] == "ACTIVE"
        assert_bond_position(current, 1500000, 2000000, 0)

        accepted = validate_success(
            api.post_bond(
                supplier["id"],
                bond_payload(
                    900000,
                    current["version"],
                    surety_name="Stale View Surety Co",
                    effective_date="2026-07-20",
                ),
                officer_headers,
            ),
            expected_status=201,
        )
        assert_bond_instrument(accepted, "ACTIVE", None, 900000)
        superseded = validate_success(api.get_bond_status(supplier["id"], officer_headers))
        assert_bond_position(superseded, 1500000, 900000, 600000, 500000, 0)
        rows_now, meta_now = validate_paginated(api.list_bonds(supplier["id"], officer_headers))
        assert_total_count(meta_now, 3, "bond instruments after the accepted repost")
        assert_bond_instrument(
            {row["id"]: row for row in rows_now}[bond_b["id"]],
            "RELEASED",
            "SUPERSEDED_BY_NEW_BOND",
            2000000,
        )

    def test_a_second_amendment_on_a_pre_amendment_view_is_told_its_view_is_stale(
        self, api, world, officer_headers, examiner_headers
    ):
        """The 412 at priority 61 stands in front of the 422 the refreshed client then earns.

        PRD: "Opening an amendment of a filed return requires `expected_return_version`, carrying
        the client's last observed `version` of the `MonthlyReturn` being amended. If that value
        does not equal that return's current `version`, the request is rejected with
        `ERR_STALE_RETURN_VERSION` (HTTP 412) and no amendment row is created."
        PRD: "The target must additionally be the newest non-superseded return of its
        filer-and-period chain, and must not itself be an amendment that has already been amended;
        a violation is refused with `ERR_AMENDMENT_TARGET_INVALID` (HTTP 422)."
        PRD: "Opening an amendment creates a **new** draft return with the same `licensee_id` and
        `period_month`, whose `amends_return_id` points at the target and whose
        `amendment_sequence` is the target's `amendment_sequence` plus one; the target's
        `amendment_count` increases by one and its `version` increments."
        PRD: "8. **Optimistic concurrency** — the two version checks of §2.10."

        Design: Corner/cross-cutting complexity layers/a_second_amendment_carrying_the_pre_amendment_return_version_returns_412
        """
        supplier = validate_success(
            api.create_licensee(
                licensee_payload(
                    "SUPPLIER", legal_name="Amend Guard Fuel Supply LLC", fein="41-9100001"
                ),
                officer_headers,
            ),
            expected_status=201,
        )
        filer = validate_success(
            api.create_licensee(
                licensee_payload(
                    "DISTRIBUTOR", legal_name="Amend Guard Distribution Inc", fein="41-9100002"
                ),
                officer_headers,
            ),
            expected_status=201,
        )
        world.set_clock("2026-09-05T00:00:00Z")
        built = world.build_return(
            filer["id"],
            "2026-08",
            [
                {
                    "code": "SCH_2_RECEIVED_TAX_UNPAID",
                    "product": "UNDYED_DIESEL",
                    "total": 1000.00,
                    "lines": [
                        {
                            "counterparty": supplier["id"],
                            "gallons": 1000.00,
                            "date": "2026-08-08",
                            "bill_of_lading_number": "BOL-AG-9100",
                        }
                    ],
                }
            ],
            file=True,
        )
        filed_version = built.row["version"]
        assert_return_money(built.row, 1000.00, 30900, 0, 0, 30900, 0)

        amendment = validate_success(
            api.create_amendment(
                built.id,
                amendment_payload(
                    filed_version,
                    "Two August loads were reported under the wrong product",
                ),
                examiner_headers,
            ),
            expected_status=201,
        )
        assert amendment["amends_return_id"] == built.id
        assert amendment["amendment_sequence"] == 1
        assert_return_statuses(amendment, "DRAFT")

        validate_error(
            api.create_amendment(
                built.id,
                amendment_payload(filed_version, "A third look at the same August loads"),
                examiner_headers,
            ),
            ApiErrorId.STALE_RETURN_VERSION,
            expected_status=412,
        )

        target = validate_success(api.get_return(built.id, examiner_headers))
        assert_return_statuses(target, "FILED")
        assert_cents(target["tax_due_cents"], 30900, "tax_due_cents of the amended target")
        assert target["amendment_count"] == 1
        assert target["version"] == filed_version + 1
        rows, meta = validate_paginated(
            api.list_returns(examiner_headers, params={"licensee_id": filer["id"]})
        )
        assert_total_count(meta, 2, "returns of the filer after the refused amendment")
        assert sorted(ids_of(rows)) == sorted([built.id, amendment["id"]])

        validate_error(
            api.create_amendment(
                built.id,
                amendment_payload(target["version"], "A third look with a refreshed view"),
                examiner_headers,
            ),
            ApiErrorId.AMENDMENT_TARGET_INVALID,
            expected_status=422,
        )


class TestFeatureFlagDefaults:
    def test_an_omitted_variance_weighting_materialises_and_only_gates_risk_score_selection(
        self, api, world, officer_headers, manager_headers
    ):
        """The flag defaults on the stored row and is consulted only under RISK_SCORE.

        PRD: "An `AuditManager` opens a case naming `subject_licensee_id`, a `selection_method` of
        `RISK_SCORE`, `CROSS_MATCH_ESCALATION` or `ROADSIDE_REFERRAL`, a `period_start_month`, a
        `period_end_month` no earlier than the start, optionally a `risk_score_variant` of
        `VARIANCE_WEIGHTED` (the default) or `FREQUENCY_WEIGHTED`, and optionally a
        `source_discrepancy_id`."
        PRD: "`risk_score_variant` is consulted only when `selection_method` is `RISK_SCORE`; for
        the other two methods it is ignored. Under `RISK_SCORE` the subject's score in the chosen
        variant must reach 60 points, and a subject below the threshold is refused with
        `ERR_RISK_SCORE_BELOW_THRESHOLD` (HTTP 422). `selection_score` freezes the score of the
        chosen variant on the case, and is 0 for any method other than `RISK_SCORE` — the frozen
        figure documents why the case was opened even after the underlying discrepancies are worked
        and the live score moves."
        PRD: "**Two defensible readings of the same history.** The risk profile of a licensee can
        be read individually by an `AuditManager`, `TaxSupervisor` or `ReturnsExaminer`, and the
        read deliberately returns **both** scoring variants side by side together with the inputs
        that produced them: `risk_score_variance_weighted`, `risk_score_frequency_weighted`,
        `unreported_gallons_total`, `open_discrepancy_count`, `late_filing_count`,
        `dyed_violation_count`, and `audit_selection_threshold`, the selection cut-off of 60
        points."

        Design: Corner/cross-cutting complexity layers/an_audit_case_stores_the_default_variance_weighting_when_the_flag_is_omitted
        """
        referred = validate_success(
            api.create_licensee(
                licensee_payload(
                    "DISTRIBUTOR", legal_name="Flag Default Distribution Inc", fein="41-9200001"
                ),
                officer_headers,
            ),
            expected_status=201,
        )
        gated = validate_success(
            api.create_licensee(
                licensee_payload(
                    "DISTRIBUTOR", legal_name="Flag Gate Distribution Inc", fein="41-9200002"
                ),
                officer_headers,
            ),
            expected_status=201,
        )

        case = validate_success(
            api.create_audit_case(
                audit_case_payload(
                    referred["id"], "2026-06", "2026-07", selection_method="ROADSIDE_REFERRAL"
                ),
                manager_headers,
            ),
            expected_status=201,
        )
        assert case["risk_score_variant"] == "VARIANCE_WEIGHTED"
        assert_case_dimensions(case, "OPEN", "NONE")
        assert case["selection_score"] == 0

        validate_error(
            api.create_audit_case(
                audit_case_payload(
                    gated["id"], "2026-06", "2026-07", selection_method="RISK_SCORE"
                ),
                manager_headers,
            ),
            ApiErrorId.RISK_SCORE_BELOW_THRESHOLD,
            expected_status=422,
        )
        validate_error(
            api.create_audit_case(
                audit_case_payload(
                    gated["id"],
                    "2026-06",
                    "2026-07",
                    selection_method="RISK_SCORE",
                    risk_score_variant="FREQUENCY_WEIGHTED",
                ),
                manager_headers,
            ),
            ApiErrorId.RISK_SCORE_BELOW_THRESHOLD,
            expected_status=422,
        )

        profile = validate_success(api.get_risk_profile(gated["id"], manager_headers))
        assert profile["risk_score_variance_weighted"] == 0
        assert profile["risk_score_frequency_weighted"] == 0
        assert profile["open_discrepancy_count"] == 0
        assert profile["late_filing_count"] == 0
        assert profile["dyed_violation_count"] == 0
        assert_gallons(profile["unreported_gallons_total"], 0.00, "unreported_gallons_total")
        assert profile["audit_selection_threshold"] == AUDIT_SELECTION_THRESHOLD

        _rows, meta = validate_paginated(api.list_audit_cases(manager_headers))
        assert_total_count(meta, 1, "audit cases after the two refused RISK_SCORE openings")


class TestImmediateConsistency:
    def test_the_filing_response_already_carries_every_cascade_it_caused(
        self, api, world, officer_headers, examiner_headers
    ):
        """One call computes tax, interest and penalty, posts three rows and re-derives the filer.

        PRD: "*Lateness.* `filed_at` is the logical clock at the moment of filing. `days_late` is 0
        when `filed_at` is at or before `due_at`; otherwise it is the elapsed time from `due_at` to
        `filed_at` divided into whole days and rounded **up** to the next whole day, so any part of
        a day counts as a full day."
        PRD: "*Interest.* `interest_cents` is 0 when `days_late` is 0. Otherwise it is
        `tax_due_cents` multiplied by a daily interest rate of 0.00025 and by `days_late`, rounded
        half up to a whole cent. Interest accrues on tax only, never on penalty."
        PRD: "The penalty is then the greater of a statutory floor of 5000 cents and the subtotal
        multiplied by that percentage rounded half up to a whole cent."
        PRD: "*Total.* `total_remittance_cents` is `tax_due_cents` plus `interest_cents` plus
        `penalty_cents`, added as integers after each component has been rounded on its own."
        PRD: "For an **original** return — one whose `amends_return_id` is null — a `RETURN_TAX`
        entry for the full `tax_due_cents` is appended always, even when the tax is zero; an
        `INTEREST` entry for `interest_cents` is appended only when interest is greater than zero;
        and a `PENALTY` entry for `penalty_cents` is appended only when the penalty is greater than
        zero."
        PRD: "In both cases the filer's `balance_cents` is re-derived from the ledger and
        `effective_taxable_gallons_ytd` is re-derived over the licensee's filed returns."
        PRD: "When `days_late` is 1 or more **and** the return is an original, `late_filing_count`
        increases by one; a period is counted late exactly once, on its original filing, so
        amending an already-late period does not count it again."

        Design: Corner/consistency model/every_cascade_of_a_write_is_already_visible_in_that_writes_own_response
        """
        supplier = validate_success(
            api.create_licensee(
                licensee_payload(
                    "SUPPLIER", legal_name="Immediate Fuel Supply LLC", fein="41-9300001"
                ),
                officer_headers,
            ),
            expected_status=201,
        )
        filer = world.active_licensee(
            "DISTRIBUTOR", legal_name="Immediate Distribution Inc", fein="41-9300002"
        )
        world.set_clock("2026-09-24T00:00:00Z")
        draft = world.build_return(
            filer["id"],
            "2026-08",
            [
                {
                    "code": "SCH_2_RECEIVED_TAX_UNPAID",
                    "product": "UNDYED_DIESEL",
                    "total": 1000.00,
                    "lines": [
                        {
                            "counterparty": supplier["id"],
                            "gallons": 1000.00,
                            "date": "2026-08-11",
                            "bill_of_lading_number": "BOL-IM-9300",
                        }
                    ],
                }
            ],
            file=False,
        )

        filed = validate_success(api.file_return(draft.id, "I. Immediate", examiner_headers))
        assert_return_statuses(filed, "FILED", "NOT_MATCHED")
        assert_starts_at(filed["filed_at"], "2026-09-24T00:00:00", "filed_at")
        assert_return_money(filed, 1000.00, 30900, 31, 5000, 35931, 4)

        entries = world.ledger(filer["id"])
        assert_ledger_sequence(
            entries, [("RETURN_TAX", 30900), ("INTEREST", 31), ("PENALTY", 5000)]
        )
        after = world.licensee(filer["id"])
        assert_cents(after["balance_cents"], 35931, "balance_cents right after the filing")
        assert after["late_filing_count"] == 1
        assert_gallons(
            after["effective_taxable_gallons_ytd"], 1000.00, "effective_taxable_gallons_ytd"
        )
        assert_balance_matches_ledger(after, entries)

        derived = (
            "balance_cents",
            "late_filing_count",
            "effective_taxable_gallons_ytd",
            "avg_monthly_tax_liability_cents",
            "required_bond_cents",
            "posted_bond_cents",
            "bond_deficiency_cents",
            "version",
        )
        again = world.licensee(filer["id"])
        assert {field: again[field] for field in derived} == {
            field: after[field] for field in derived
        }, "a second read must not recompute the derived fields differently"
