"""The seven roles: a shared read surface, exclusive writes, identity and duties."""

import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    admin,
    all_elements_passing,
    api_client,
    asset_with_obsolete_predecessor,
    assign_root_cause,
    brand,
    brief_decision_payload,
    clearance_payload,
    coord,
    create_artwork_version_payload,
    create_brief_payload,
    create_marketing_claim_payload,
    create_printer_payload,
    create_printer_proof_payload,
    current_route,
    decide_task,
    dispute_escape,
    dispute_payload,
    element_check_by_code,
    in_review_version,
    legal,
    make_headers,
    new_approved_brief,
    new_asset,
    new_brief,
    new_claim,
    new_escape,
    new_printer,
    new_proof,
    new_version,
    printer_as,
    quality,
    raise_recovery_claim,
    read_brief,
    read_claim,
    read_element_check,
    read_task,
    read_version,
    regulatory,
    submit,
    task_decision_payload,
    tasks_by_discipline,
    validate_error,
    validate_paginated,
    validate_success,
    verify,
    verify_elements_payload,
    waiver_payload,
)

NO_AUTH_HEADERS = {"Content-Type": "application/json"}
ROLE_WITHOUT_USER_HEADERS = {
    "X-User-Role": "PackagingCoordinator",
    "Content-Type": "application/json",
}


class TestSharedReadSurfaceIsRoleBlind:
    """Seven requests differing only in the role header, one identical row back."""

    def test_all_seven_roles_read_the_same_brief(self):
        """Every role, the print vendor included, sees the same SKU, status and count.

        PRD §2.2: "Every read endpoint in the service is open to all seven roles."

        PRD §2.2: "`PrinterRep` is the one exception and is entity-backed. When
        `X-User-Role` is `PrinterRep`, `X-User-ID` is the `id` of the acting `Printer`
        row; ownership checks on any resource that references a `Printer` compare the
        resource's `printer_id` field against `X-User-ID`."

        Design: Corner/rbac/every_one_of_the_seven_roles_reads_the_shared_get_surface_and_sees_the_same_row
        """
        brief = new_approved_brief()
        printer = new_printer()

        every_role = [
            coord(),
            brand(),
            legal(),
            regulatory(),
            quality(),
            printer_as(printer),
            admin(),
        ]
        assert len(every_role) == 7
        for headers in every_role:
            seen = validate_success(api_client.get_brief(brief["id"], headers), 200)
            assert seen["id"] == brief["id"]
            assert seen["sku_code"] == "SKU-1001"
            assert seen["status"] == "APPROVED"
            assert seen["asset_count"] == 0
            assert seen["version"] == 2

        vendors, vendor_meta = validate_paginated(
            api_client.list_printers(
                printer_as(printer), params={"certification_status": "CERTIFIED"}
            )
        )
        assert len(vendors) == 1
        assert vendor_meta["total_count"] == 1
        assert vendors[0]["id"] == printer["id"]
        assert vendors[0]["name"] == "Cascade Print Co"
        assert vendors[0]["performance_score"] == pytest.approx(100.0, abs=0.01)

        assets, asset_meta = validate_paginated(
            api_client.list_artwork_assets(
                printer_as(printer), params={"brief_id": brief["id"]}
            )
        )
        assert assets == []
        assert asset_meta["total_count"] == 0


class TestExclusiveWritesAreNotReachableAcrossRoles:
    """Eight crossings refused before any state check, and the admin is no superuser."""

    def test_platform_admin_is_no_override_yet_still_onboards_vendors(self):
        """Eight writes are 403s that change nothing, then the admin's own write lands.

        PRD §2.2: "`PlatformAdmin` is deliberately **not** a hierarchical override — it
        cannot create briefs, decide review tasks, waive element checks or submit proofs,
        and attempting any of those yields `ERR_UNAUTHORIZED`."

        PRD §2.2: "When both headers are well-formed but the named role is not among the
        roles authorised for the endpoint being called, the rejection is
        `ERR_UNAUTHORIZED` with HTTP 403."

        Design: Corner/rbac/roles_cannot_reach_each_others_exclusive_writes_and_platform_admin_is_no_override
        """
        brief = new_brief()
        assert brief["status"] == "DRAFT"
        asset = new_asset(brief["id"])
        version = new_version(
            asset,
            mandatory_elements=all_elements_passing(
                allergen_statement={
                    "text": "Contains milk and soya.",
                    "allergen_emphasis": False,
                }
            ),
        )
        verify(version["id"])
        failing = element_check_by_code(version["id"], "ALLERGEN_STATEMENT")
        assert failing["result"] == "FAIL"
        claim = new_claim()
        assert claim["legal_status"] == "DRAFT"

        validate_error(
            api_client.create_brief(
                create_brief_payload(
                    sku_code="SKU-2002", product_name="Northgate Cocoa Sachet 20g"
                ),
                admin(),
            ),
            ApiErrorId.ERR_UNAUTHORIZED.value,
            403,
        )
        validate_error(
            api_client.decide_brief(
                brief["id"], brief_decision_payload("APPROVED"), coord()
            ),
            ApiErrorId.ERR_UNAUTHORIZED.value,
            403,
        )
        validate_error(
            api_client.decide_brief(
                brief["id"], brief_decision_payload("APPROVED"), admin()
            ),
            ApiErrorId.ERR_UNAUTHORIZED.value,
            403,
        )
        validate_error(
            api_client.create_printer(
                create_printer_payload(
                    name="Backdoor Print Ltd",
                    certified_substrates=["COATED_PAPER"],
                    recovery_liability_cap_cents=100000,
                ),
                coord(),
            ),
            ApiErrorId.ERR_UNAUTHORIZED.value,
            403,
        )
        validate_error(
            api_client.create_marketing_claim(
                create_marketing_claim_payload(
                    claim_code="CLM-NAS-02",
                    claim_text="No added sugar.",
                    substantiation_ref="DOSSIER-NAS-2026-02",
                ),
                legal(),
            ),
            ApiErrorId.ERR_UNAUTHORIZED.value,
            403,
        )
        validate_error(
            api_client.decide_claim_clearance(
                claim["id"],
                clearance_payload(
                    "CLEARED",
                    cleared_from_utc="2026-08-01T00:00:00Z",
                    cleared_until_utc="2027-08-01T00:00:00Z",
                ),
                regulatory(),
            ),
            ApiErrorId.ERR_UNAUTHORIZED.value,
            403,
        )
        validate_error(
            api_client.waive_element_check(
                failing["id"],
                waiver_payload(
                    waiver_justification=(
                        "Quality is happy to carry the allergen risk."
                    )
                ),
                quality(),
            ),
            ApiErrorId.ERR_UNAUTHORIZED.value,
            403,
        )
        validate_error(
            api_client.verify_elements(
                version["id"],
                verify_elements_payload(verification_note="Admin re-verification."),
                admin(),
            ),
            ApiErrorId.ERR_UNAUTHORIZED.value,
            403,
        )

        assert read_brief(brief["id"])["status"] == "DRAFT"
        assert read_brief(brief["id"])["version"] == 1
        untouched = read_element_check(failing["id"])
        assert untouched["result"] == "FAIL"
        assert untouched["waived_by_user_id"] is None
        assert untouched["waiver_justification"] is None
        assert read_claim(claim["id"])["legal_status"] == "DRAFT"
        assert read_version(version["id"])["check_run_no"] == 1
        _rows, meta = validate_paginated(api_client.list_printers(admin()))
        assert meta["total_count"] == 0

        onboarded = validate_success(
            api_client.create_printer(create_printer_payload(), admin()), 201
        )
        assert onboarded["name"] == "Cascade Print Co"
        assert onboarded["certification_status"] == "CERTIFIED"
        assert onboarded["performance_score"] == pytest.approx(100.0, abs=0.01)
        assert onboarded["escape_count"] == 0
        assert onboarded["recovery_balance_cents"] == 0


class TestDisciplineBindingOutranksTheStageGate:
    """The decision endpoint admits four roles; each task admits exactly one."""

    def test_the_same_reviewer_gets_a_403_on_one_task_and_a_409_on_another(self):
        """A wrong discipline is 403; the right discipline in a closed stage is 409.

        PRD §2.2: "The same `ERR_UNAUTHORIZED` code covers the finer-grained discipline
        binding on review decisions: a reviewer role that does not match the reviewing
        discipline recorded on the task it is trying to decide is refused with that code,
        because the endpoint is shared across four reviewer roles while each individual
        task is not."

        PRD §3.5: "The task's `is_active` must be true, its `stage_no` must equal the
        pass's `current_stage_no`, and the pass's `status` must be `IN_PROGRESS`; any of
        those failing is `ERR_ROUTE_STAGE_NOT_ACTIVE`"

        Design: Corner/rbac/a_reviewer_cannot_decide_a_task_of_another_discipline_and_discipline_outranks_stage
        """
        _brief, _asset, version = in_review_version()
        route = current_route(version["id"])
        tasks = tasks_by_discipline(route["id"])
        assert tasks["QUALITY"]["stage_no"] == 3
        assert tasks["QUALITY"]["is_active"] is False

        validate_error(
            api_client.decide_review_task(
                tasks["BRAND"]["id"],
                task_decision_payload("APPROVED", comment="Looks on-brand to me."),
                legal(),
            ),
            ApiErrorId.ERR_UNAUTHORIZED.value,
            403,
        )
        validate_error(
            api_client.decide_review_task(
                tasks["REGULATORY"]["id"],
                task_decision_payload("APPROVED", comment="Regulatory copy approved."),
                quality(),
            ),
            ApiErrorId.ERR_UNAUTHORIZED.value,
            403,
        )
        validate_error(
            api_client.decide_review_task(
                tasks["QUALITY"]["id"],
                task_decision_payload("APPROVED", comment="Quality sign-off."),
                quality(),
            ),
            ApiErrorId.ERR_ROUTE_STAGE_NOT_ACTIVE.value,
            409,
        )

        decided = decide_task(
            tasks["BRAND"], "APPROVED", comment="Brand identity approved."
        )
        assert decided["decision"] == "APPROVED"
        assert decided["decided_by_user_id"] == "u_brand"

        for discipline in ("REGULATORY", "QUALITY"):
            still_open = read_task(tasks[discipline]["id"])
            assert still_open["decision"] == "PENDING"
            assert still_open["decided_at"] is None
            assert still_open["decided_by_user_id"] is None
        assert read_task(tasks["QUALITY"]["id"])["is_active"] is False


class TestPrinterRepIdentityIsCheckedInBothDirections:
    """The entity-backed identity is an equality, not a membership test."""

    def test_neither_vendor_can_act_on_the_other_s_row(self):
        """Both mismatch directions are 403s, and the matching vendor then succeeds.

        PRD §2.2: "Concretely, a proof submission whose `printer_id` differs from the
        caller's `X-User-ID`, and a dispute raised on an escape whose `printer_id` differs
        from the caller's `X-User-ID`, are both rejected with
        `ERR_PRINTER_IDENTITY_MISMATCH` and HTTP 403."

        PRD §3.9: "The `PrinterRep` whose `X-User-ID` equals the escape's `printer_id` —
        anyone else being refused with `ERR_PRINTER_IDENTITY_MISMATCH` — supplies a
        non-empty `dispute_reason`, which is stored, and `dispute_count` is incremented by
        1."

        Design: Corner/rbac/a_printer_rep_cannot_act_for_a_printer_that_is_not_its_own_row
        """
        _brief, _asset, v1, v2 = asset_with_obsolete_predecessor()
        assert v1["state"] == "OBSOLETE_PENDING"
        assert v2["state"] == "APPROVED"
        printer_a = new_printer()
        printer_b = new_printer(
            name="Harbourline Litho",
            color_standard="ISO12647",
            certified_substrates=["COATED_PAPER"],
        )

        escape = new_escape(
            v1["id"], printer_a, discovered_stage="PACKING", units_affected=2000
        )
        assert escape["investigation_fee_cents"] == 60000
        assign_root_cause(escape["id"], "PRINTER", 1.00)
        claimed = raise_recovery_claim(escape["id"])
        # 84000 reprint + 14000 scrap + 0 freight + 60000 investigation at share 1.00.
        assert claimed["state"] == "RECOVERY_CLAIMED"
        assert claimed["provisional_recovery_cents"] == 158000
        assert claimed["dispute_count"] == 0

        validate_error(
            api_client.create_printer_proof(
                create_printer_proof_payload(v2["id"], printer_a["id"]),
                printer_as(printer_b),
            ),
            ApiErrorId.ERR_PRINTER_IDENTITY_MISMATCH.value,
            403,
        )
        validate_error(
            api_client.create_printer_proof(
                create_printer_proof_payload(v2["id"], printer_b["id"]),
                printer_as(printer_a),
            ),
            ApiErrorId.ERR_PRINTER_IDENTITY_MISMATCH.value,
            403,
        )
        validate_error(
            api_client.dispute_escape(
                escape["id"],
                dispute_payload(dispute_reason="Not our press run."),
                printer_as(printer_b),
            ),
            ApiErrorId.ERR_PRINTER_IDENTITY_MISMATCH.value,
            403,
        )

        disputed = dispute_escape(
            escape["id"],
            printer_a,
            dispute_reason=(
                "The brand approved the French panel on the US artwork."
            ),
        )
        assert disputed["state"] == "DISPUTED"
        assert disputed["dispute_count"] == 1

        proof = new_proof(v2["id"], printer_a)
        assert proof["proof_no"] == 1
        assert proof["proof_state"] == "PROOF_IN_REVIEW"
        assert proof["color_status"] == "COLOR_PENDING"
        assert proof["substrate_status"] == "SUBSTRATE_PENDING"
        assert proof["printer_id"] == printer_a["id"]

        rows, meta = validate_paginated(
            api_client.list_printer_proofs(
                admin(), params={"printer_id": printer_b["id"]}
            )
        )
        assert rows == []
        assert meta["total_count"] == 0


class TestSegregationOfDutiesHasTwoLimbs:
    """The author cannot decide, and one decider cannot decide twice on a pass."""

    def test_the_author_and_the_repeat_decider_are_both_refused(self):
        """u_dual is barred as author; u_brand is barred on its second task of the pass.

        PRD §3.5: "Finally, segregation of duties: the deciding `X-User-ID` may be neither
        the routed version's `author_user_id` nor an identifier already recorded as
        `decided_by_user_id` on any other task of the same pass, and either violation is
        `ERR_SEGREGATION_OF_DUTIES`."

        Design: Corner/rbac/segregation_of_duties_bars_the_version_author_and_the_second_task_of_one_decider
        """
        brief = new_approved_brief()
        asset = new_asset(brief["id"])
        version = validate_success(
            api_client.create_artwork_version(
                asset["id"],
                create_artwork_version_payload(asset["version"]),
                make_headers("u_dual", "PackagingCoordinator"),
            ),
            201,
        )
        assert version["author_user_id"] == "u_dual"

        verify(version["id"])
        submit(version["id"])
        route = current_route(version["id"])
        tasks = tasks_by_discipline(route["id"])

        validate_error(
            api_client.decide_review_task(
                tasks["BRAND"]["id"],
                task_decision_payload(
                    "APPROVED", comment="My own artwork looks great."
                ),
                make_headers("u_dual", "BrandReviewer"),
            ),
            ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value,
            403,
        )

        brand_done = decide_task(
            tasks["BRAND"], "APPROVED", comment="Brand identity approved."
        )
        assert brand_done["decision"] == "APPROVED"
        assert brand_done["decided_by_user_id"] == "u_brand"

        validate_error(
            api_client.decide_review_task(
                tasks["REGULATORY"]["id"],
                task_decision_payload(
                    "APPROVED", comment="And the regulatory copy too."
                ),
                make_headers("u_brand", "RegulatoryReviewer"),
            ),
            ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value,
            403,
        )

        reg_done = decide_task(
            tasks["REGULATORY"], "APPROVED", comment="Regulatory copy approved."
        )
        assert reg_done["decision"] == "APPROVED"
        assert reg_done["decided_by_user_id"] == "u_reg"

        rows, meta = validate_paginated(
            api_client.list_review_tasks(
                coord(), params={"review_route_id": route["id"], "limit": 100}
            )
        )
        assert meta["total_count"] == 4
        deciders = {
            row["discipline"]: row["decided_by_user_id"]
            for row in rows
            if row["decision"] != "PENDING"
        }
        assert deciders == {"BRAND": "u_brand", "REGULATORY": "u_reg"}
        assert "u_dual" not in [row["decided_by_user_id"] for row in rows]


class TestAuthenticationOutranksEveryLookup:
    """Priority one: no headers, an unknown role, and a role with no identity."""

    def test_three_header_faults_are_all_four_hundred_ones(self):
        """A missing header beats a missing row, and an unknown role is not a 403.

        PRD §2.2: "If either header is absent, or if `X-User-Role` is not one of the seven
        role names enumerated below, the request is rejected with
        `ERR_MISSING_AUTH_HEADERS` and HTTP 401."

        PRD §2.7: "First, authentication and coarse authorisation: header presence and
        role validity (`ERR_MISSING_AUTH_HEADERS`), then endpoint role membership
        (`ERR_UNAUTHORIZED`)."

        Design: Corner/rbac/requests_missing_auth_headers_or_carrying_an_unknown_role_are_401_before_any_lookup
        """
        brief = new_approved_brief()

        validate_error(
            api_client.get_brief(NON_EXISTENT_UUID, NO_AUTH_HEADERS),
            ApiErrorId.ERR_MISSING_AUTH_HEADERS.value,
            401,
        )
        validate_error(
            api_client.list_briefs(make_headers("u_audit", "Auditor")),
            ApiErrorId.ERR_MISSING_AUTH_HEADERS.value,
            401,
        )
        validate_error(
            api_client.create_brief(
                create_brief_payload(sku_code="SKU-3003"),
                ROLE_WITHOUT_USER_HEADERS,
            ),
            ApiErrorId.ERR_MISSING_AUTH_HEADERS.value,
            401,
        )

        rows, meta = validate_paginated(api_client.list_briefs(coord()))
        assert len(rows) == 1
        assert meta["total_count"] == 1
        assert rows[0]["sku_code"] == "SKU-1001"

        healthy = validate_success(api_client.get_brief(brief["id"], coord()), 200)
        assert healthy["sku_code"] == "SKU-1001"
        assert healthy["status"] == "APPROVED"
