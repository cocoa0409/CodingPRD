"""Kit revision pipeline: BOM wholesale replacement, activation gate,
supersession chains, approval side effects, and the plan-version OCC guard.

Covers PRD §2.8 (OCC), §3.2 (plans, revisions, BOM).
"""
from test_helpers import (
    ApiErrorId,
    api_client,
    approve_revision,
    assert_kit_revision,
    bom_line,
    create_client,
    create_component,
    create_kit_revision_payload,
    create_plan,
    create_revision,
    get_plan,
    make_client_ops_headers,
    put_bom,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
    TEST_USERS,
)

ADMIN = TEST_USERS["platform_admin_headers"]
WAREHOUSE = TEST_USERS["warehouse_ops_headers"]


class TestBomLineReplacement:
    def test_kit_bom_line_set_replacement_is_wholesale(self):
        """PRD §3.2: "The previous lines of the revision are deleted and
        replaced wholesale."

        Design: Corner/entities/kit_bom_line_set_replacement_is_wholesale
        """
        set_clock()
        client = create_client(name="KB Client", billing_email="kb@acme.test")
        comp_a = create_component("CMP-KBA", name="KB A")
        comp_b = create_component("CMP-KBB", name="KB B")
        plan = create_plan(client["id"], "PL-KB", name="KB Box",
                           shipping_weight_grams=500)
        revision = create_revision(plan["id"], client["id"])
        put_bom(revision["id"], client["id"], [bom_line(comp_a["id"], 1)])

        put_bom(revision["id"], client["id"], [bom_line(comp_b["id"], 3)])
        resp = api_client.list_bom_lines(revision["id"],
                                         make_client_ops_headers(client["id"]))
        lines, meta = validate_paginated(resp)
        assert len(lines) == 1 and meta["total_count"] == 1, (
            f"wholesale replace must leave exactly 1 line, got {len(lines)}"
        )
        assert lines[0]["component_id"] == comp_b["id"]
        assert lines[0]["qty_per_box"] == 3
        assert all(line["component_id"] != comp_a["id"] for line in lines), \
            "the replaced component's line must be gone (wholesale, not merge)"


class TestPlanActivationGate:
    def test_box_plan_activate_without_approved_revision_rejected(self):
        """PRD §3.2: "Activation moves the plan `DRAFT → ACTIVE` and requires
        `active_revision_id` to be set — a plan with no approved revision is
        rejected with `ERR_PLAN_HAS_NO_APPROVED_REVISION`"

        Design: Corner/state_machines/box_plan_activate_without_approved_revision_rejected
        """
        set_clock()
        client = create_client(name="SM3 Client", billing_email="sm3@acme.test")
        plan = create_plan(client["id"], "PL-SM3", name="SM3 Box",
                           shipping_weight_grams=500)
        resp = api_client.activate_box_plan(plan["id"],
                                            make_client_ops_headers(client["id"]))
        validate_error(resp, ApiErrorId.ERR_PLAN_HAS_NO_APPROVED_REVISION)
        assert get_plan(plan["id"], client["id"])["status"] == "DRAFT", \
            "rejected activation must leave the plan DRAFT"


class TestRevisionApprovalSideEffects:
    def test_revision_approve_retires_prior_approved(self):
        """PRD §3.2: "the previously `APPROVED` revision of the same plan, if
        one exists, automatically transitions `APPROVED → RETIRED`". PRD §3.2:
        "Each revision receives a `revision_no`, a per-plan monotone counter
        starting at 1 for the plan's first revision and set to one greater than
        the highest existing `revision_no` of the plan thereafter."

        Design: Corner/state_machines/revision_approve_retires_prior_approved
        """
        set_clock()
        client = create_client(name="SM6 Client", billing_email="sm6@acme.test")
        component = create_component("CMP-SM6", name="SM6 widget")
        plan = create_plan(client["id"], "PL-SM6", name="SM6 Box",
                           shipping_weight_grams=500)
        rev1 = create_revision(plan["id"], client["id"])
        put_bom(rev1["id"], client["id"], [bom_line(component["id"], 1)])
        approve_revision(rev1["id"], client["id"])
        rev2 = create_revision(plan["id"], client["id"])
        assert rev2["revision_no"] == 2, \
            f"second revision must carry revision_no 2, got {rev2['revision_no']}"
        put_bom(rev2["id"], client["id"], [bom_line(component["id"], 2)])

        approved2 = approve_revision(rev2["id"], client["id"])
        assert_kit_revision(approved2)
        assert approved2["status"] == "APPROVED"

        rev1_after = validate_success(
            api_client.get_kit_revision(rev1["id"],
                                        make_client_ops_headers(client["id"])))
        assert rev1_after["status"] == "RETIRED", (
            f"prior APPROVED revision must auto-retire, got {rev1_after['status']}"
        )
        plan_after = get_plan(plan["id"], client["id"])
        assert plan_after["active_revision_id"] == rev2["id"], \
            "plan active_revision_id must repoint to the newly approved revision"


class TestSupersessionChain:
    def test_kit_revision_supersession_chain(self):
        """PRD §3.2: "If the plan currently holds another `DRAFT` revision,
        that older draft automatically transitions `DRAFT → RETIRED` at the
        moment of creation, and the new revision's `supersedes_revision_id`
        (null when nothing was superseded) points at the retired draft".
        PRD §3.2: "a global revision listing supports `plan_id`,
        `supersedes_revision_id`, and `status` filters — the last of these
        enabling supersession lookups that answer "which revision replaced
        this one"."

        Design: Corner/endpoints/kit_revision_supersession_chain
        """
        set_clock()
        client = create_client(name="EP3 Client", billing_email="ep3@acme.test")
        headers = make_client_ops_headers(client["id"])
        plan = create_plan(client["id"], "PL-EP3", name="EP3 Box",
                           shipping_weight_grams=500)
        rev1 = create_revision(plan["id"], client["id"])

        plan_now = get_plan(plan["id"], client["id"])
        rev2 = validate_success(
            api_client.create_kit_revision(
                plan["id"],
                create_kit_revision_payload(plan_now["version"]),
                headers),
            expected_status=201)
        assert rev2["supersedes_revision_id"] == rev1["id"], \
            "the new revision must point at the retired draft it superseded"

        rev1_after = validate_success(api_client.get_kit_revision(rev1["id"], headers))
        assert rev1_after["status"] == "RETIRED", \
            f"superseded draft must retire, got {rev1_after['status']}"

        resp = api_client.list_kit_revisions(
            headers, params={"supersedes_revision_id": rev1["id"]})
        successors, meta = validate_paginated(resp)
        assert len(successors) == 1 and successors[0]["id"] == rev2["id"], \
            "reverse supersession lookup must return exactly the replacing revision"


class TestRevisionCreateOcc:
    def test_occ_revision_create_stale_plan_version_rejected(self):
        """PRD §2.8: "Creating a kit revision against a box plan requires the
        request to carry `expected_box_plan_version` holding the plan's
        `version` as the client last observed it. If the plan's `version` has
        advanced since that observation, the create is rejected with
        `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_layers/occ_revision_create_stale_plan_version_rejected
        """
        set_clock()
        client = create_client(name="X1 Client", billing_email="x1@acme.test")
        headers = make_client_ops_headers(client["id"])
        plan = create_plan(client["id"], "PL-X1", name="X1 Box",
                           shipping_weight_grams=500)
        observed_version = plan["version"]
        validate_success(
            api_client.create_kit_revision(
                plan["id"], create_kit_revision_payload(observed_version), headers),
            expected_status=201)

        replay = api_client.create_kit_revision(
            plan["id"], create_kit_revision_payload(observed_version), headers)
        validate_error(replay, ApiErrorId.ERR_STALE_VERSION)

        resp = api_client.list_plan_kit_revisions(plan["id"], headers)
        revisions, meta = validate_paginated(resp)
        assert meta["total_count"] == 1 and len(revisions) == 1, (
            f"stale replay must not persist another revision, "
            f"got {meta['total_count']}"
        )
