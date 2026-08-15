"""Authentication, authorization (RBAC), entity-backed welder identity, and
the two segregation-of-duties rules."""
from test_helpers import (
    DETAILER,
    EOR,
    GC_PM,
    QC,
    ApiErrorId,
    api_client,
    create_drawing,
    create_in_shop_piece,
    create_job,
    create_job_payload,
    create_piece_payload,
    create_sequence,
    create_weld_payload,
    create_welder,
    log_weld,
    make_eor_headers,
    make_qc_inspector_headers,
    make_welder_headers,
    schedule_weld_inspection,
    setup_fabrication_ready,
    submit_drawing,
    validate_error,
    validate_success,
)


class TestAuthentication:

    def test_missing_role_header_unauthenticated(self):
        """PRD section 2.1: "Every request must carry two headers: `X-User-ID`,
        identifying the acting user, and `X-User-Role`, declaring the caller's
        operational capacity. A request missing either header, or carrying a
        role the system does not recognize, is rejected with
        `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/validations/missing_role_header_unauthenticated
        """
        resp = api_client.create_job(
            create_job_payload(name="Job V1"), {"X-User-ID": "op-1"}
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


class TestRoleDenial:

    def test_detailer_job_create_forbidden(self):
        """PRD section 2.1: "Each endpoint admits a fixed set of roles (see
        §4); a caller whose role is not admitted is rejected with
        `ERR_FORBIDDEN` (HTTP 403)."
        PRD section 4: the `POST /jobs` row lists `FABRICATOR_ADMIN` as its
        only authorized role.

        Design: Corner/validations/detailer_job_create_forbidden
        """
        resp = api_client.create_job(
            create_job_payload(name="Job V2"), DETAILER
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_inspector_decide_drawing_forbidden(self):
        """PRD section 2.1: "Each endpoint admits a fixed set of roles (see
        §4); a caller whose role is not admitted is rejected with
        `ERR_FORBIDDEN` (HTTP 403)."
        PRD section 4: the `POST /shop-drawings/{id}/decide` row lists `EOR`
        as its only authorized role.

        Design: Corner/rbac/inspector_decide_drawing_forbidden
        """
        job = create_job("Job RB1")
        drawing = create_drawing(job["id"], "D-1")
        submit_drawing(drawing["id"])
        resp = api_client.decide_drawing(
            drawing["id"], {"decision": "APPROVE"}, QC
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_gc_pm_cannot_create_pieces(self):
        """PRD section 2.1: "Each endpoint admits a fixed set of roles (see
        §4); a caller whose role is not admitted is rejected with
        `ERR_FORBIDDEN` (HTTP 403)."
        PRD section 4: the `POST /pieces` row lists `FOREMAN` as its only
        authorized role.

        Design: Corner/rbac/gc_pm_cannot_create_pieces
        """
        job = create_job("Job RB3")
        drawing = create_drawing(job["id"], "D-1")
        sequence = create_sequence(job["id"], 1)
        resp = api_client.create_piece(
            create_piece_payload(job["id"], drawing["id"], sequence["id"]),
            GC_PM,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


class TestSegregationOfDuties:

    def test_drawing_self_approval_forbidden(self):
        """PRD section 3.2: "The decision belongs to the `EOR`, who supplies a
        `decision` of `APPROVE` or `REJECT`; either way the decider is recorded
        as `decided_by_user_id`, and either way the decider must not be the
        submitter — an `EOR` deciding a drawing whose `submitted_by_user_id`
        equals their own `X-User-ID` is rejected with
        `ERR_SELF_APPROVAL_FORBIDDEN`."

        Design: Corner/validations/drawing_self_approval_forbidden
        """
        job = create_job("Job V3")
        drawing = create_drawing(job["id"], "D-1")
        submit_drawing(drawing["id"], submitter="det-9")
        resp = api_client.decide_drawing(
            drawing["id"], {"decision": "APPROVE"}, make_eor_headers("det-9")
        )
        validate_error(resp, ApiErrorId.ERR_SELF_APPROVAL_FORBIDDEN)
        after = validate_success(api_client.get_shop_drawing(drawing["id"], EOR))
        assert after["status"] == "SUBMITTED", \
            "a rejected self-approval must leave the drawing SUBMITTED"

    def test_weld_inspector_segregation_enforced(self):
        """PRD section 3.6: "For weld inspections a segregation rule applies:
        the inspector's `X-User-ID` must not equal the weld's `welder_id` — no
        one inspects their own weld — with violations rejected as
        `ERR_SEGREGATION_OF_DUTIES`."

        Design: Corner/validations/weld_inspector_segregation_enforced
        """
        ctx = setup_fabrication_ready("Job V4")
        piece = create_in_shop_piece(ctx, "P1", 800)
        welder = create_welder("Weld Eight")
        weld = log_weld(piece["id"], welder["id"])
        inspection = schedule_weld_inspection(
            ctx["job"]["id"], weld["id"], "WELD_VISUAL"
        )
        # The inspector presents the welder's own id.
        resp = api_client.submit_inspection(
            inspection["id"], {"outcome": "PASSED"},
            make_qc_inspector_headers(welder["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
        after = validate_success(api_client.get_inspection(inspection["id"], QC))
        assert after["status"] == "SCHEDULED", \
            "a segregated submit must leave the inspection SCHEDULED"


class TestWelderEntityBackedIdentity:

    def test_welder_cannot_weld_for_other_welder(self):
        """PRD section 3.5: "Welding itself is logged by a `WELDER`, and the
        identity rule is strict: the payload's `welder_id` must equal the
        caller's `X-User-ID`, or the request is rejected with `ERR_FORBIDDEN`."
        PRD section 2.1: "When `X-User-Role` is `WELDER`, `X-User-ID` is the
        `id` of the acting Welder record; ownership checks on any resource that
        references a welder compare the resource's `welder_id` field against
        `X-User-ID`."

        Design: Corner/rbac/welder_cannot_weld_for_other_welder
        """
        ctx = setup_fabrication_ready("Job RB2")
        piece = create_in_shop_piece(ctx, "P1", 800)
        welder_a = create_welder("Welder A")
        welder_b = create_welder("Welder B")
        # Caller is welder A but the payload names welder B.
        resp = api_client.create_weld(
            create_weld_payload(piece["id"], welder_b["id"]),
            make_welder_headers(welder_a["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
