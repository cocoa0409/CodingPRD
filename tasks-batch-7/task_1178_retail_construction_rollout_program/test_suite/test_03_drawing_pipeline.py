"""Drawing-set revision numbering, approval supersession, RBAC on drawing
approval, and the site submit-design drawing gate."""
from test_helpers import (
    ApiErrorId,
    assert_drawing_set,
    create_approved_drawing_set,
    create_drawing_set,
    read_site,
    setup_program_with_market,
    setup_site_in_design,
    validate_error,
    validate_success,
)


class TestDrawingRevisions:
    def test_drawing_revision_auto_increments_per_jurisdiction(
            self, api, design_manager_headers):
        """PRD §3.2: "Revision numbering is automatic per
        program-and-jurisdiction pair: the `revision` of a new set is one more
        than the highest existing revision for that pair, and its
        `review_round` starts at 1."

        Design: Corner/entities/c_drawing_revision_auto_increments_per_jurisdiction
        """
        ctx = setup_program_with_market()
        ds1 = create_drawing_set(ctx["program"]["id"], jurisdiction_code="TX-DAL")
        ds2 = create_drawing_set(ctx["program"]["id"], jurisdiction_code="TX-DAL")
        ds3 = create_drawing_set(ctx["program"]["id"], jurisdiction_code="TX-FTW")
        assert_drawing_set(ds1)
        assert ds1["revision"] == 1
        assert ds2["revision"] == 2
        assert ds3["revision"] == 1, "revision numbering restarts per jurisdiction"

    def test_drawing_approve_supersedes_prior_revision(self, api,
                                                       design_manager_headers):
        """PRD §3.2: "Approval moves it to `APPROVED` and enforces
        single-currency of approved drawings: any other `APPROVED` set for the
        same program and jurisdiction moves to `SUPERSEDED`, and the newly
        approved set's `supersedes_set_id` is pinned to the superseded set's
        `id`, or left null when nothing was superseded."

        Design: Corner/state_machines/c_drawing_approve_supersedes_prior_revision
        """
        ctx = setup_program_with_market()
        ds1 = create_approved_drawing_set(ctx["program"]["id"],
                                          jurisdiction_code="TX-DAL")
        ds2 = create_drawing_set(ctx["program"]["id"], jurisdiction_code="TX-DAL",
                                 submit=True)

        resp = api.approve_drawing_set(ds2["id"], headers=design_manager_headers)
        ds2_after = validate_success(resp)
        assert ds2_after["status"] == "APPROVED"
        assert ds2_after["supersedes_set_id"] == ds1["id"]

        resp = api.get_drawing_set(ds1["id"], headers=design_manager_headers)
        assert validate_success(resp)["status"] == "SUPERSEDED"

    def test_operations_lead_cannot_approve_drawing(self, api, design_manager_headers,
                                                    operations_lead_headers):
        """PRD §2.1: "A request whose role is well-formed but not permitted
        for the target endpoint is rejected with `ERR_UNAUTHORIZED_ROLE`."
        PRD §4: drawing-set approve is authorized for DesignManager.

        Design: Corner/rbac/c_operations_lead_cannot_approve_drawing
        """
        ctx = setup_program_with_market()
        ds = create_drawing_set(ctx["program"]["id"], jurisdiction_code="TX-DAL",
                                submit=True)
        resp = api.approve_drawing_set(ds["id"], headers=operations_lead_headers)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)
        resp = api.get_drawing_set(ds["id"], headers=design_manager_headers)
        assert validate_success(resp)["status"] == "SUBMITTED"


class TestSubmitDesignGate:
    def test_submit_design_requires_approved_drawing_set(self, api,
                                                         design_manager_headers):
        """PRD §3.2: "Submitting the design moves it from `DESIGN` to
        `PERMITTING`, and that step is gated on drawings: an `APPROVED`
        drawing set must exist whose program matches the site's program and
        whose `jurisdiction_code` matches the site's `municipality_code`;
        without one the transition is rejected with
        `ERR_DRAWING_NOT_APPROVED`."

        Design: Difficulty/cross_entity_state_dependency/site_submit_design_requires_approved_drawing_set
        """
        ctx = setup_site_in_design(with_drawing_submitted=True)
        site_id = ctx["site"]["id"]

        # Drawing set merely SUBMITTED: the gate rejects the transition.
        resp = api.submit_site_design(site_id, headers=design_manager_headers)
        validate_error(resp, ApiErrorId.ERR_DRAWING_NOT_APPROVED)
        assert read_site(site_id)["status"] == "DESIGN"

        # Once the drawing set reaches APPROVED, the same transition succeeds.
        resp = api.approve_drawing_set(ctx["ds"]["id"], headers=design_manager_headers)
        validate_success(resp)
        resp = api.submit_site_design(site_id, headers=design_manager_headers)
        assert validate_success(resp)["status"] == "PERMITTING"

    def test_submit_design_rejects_drawing_from_other_jurisdiction(
            self, api, design_manager_headers):
        """PRD §3.2: "an `APPROVED` drawing set must exist whose program
        matches the site's program and whose `jurisdiction_code` matches the
        site's `municipality_code`; without one the transition is rejected
        with `ERR_DRAWING_NOT_APPROVED`."

        Design: Difficulty/cross_entity_state_dependency/site_submit_design_requires_approved_drawing_set
        """
        ctx = setup_site_in_design(jurisdiction_code="TX-DAL")
        # Approved drawing exists, but for a different municipality.
        create_approved_drawing_set(ctx["program"]["id"], jurisdiction_code="TX-FTW")

        resp = api.submit_site_design(ctx["site"]["id"], headers=design_manager_headers)
        validate_error(resp, ApiErrorId.ERR_DRAWING_NOT_APPROVED)
        assert read_site(ctx["site"]["id"])["status"] == "DESIGN"
