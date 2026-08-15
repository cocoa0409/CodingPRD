"""Authentication context, role authorization, validation precedence,
per-resource 404s, and the error envelope shape."""
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    add_tray,
    approve_request,
    coordinator,
    create_case,
    create_credentialed_rep,
    create_rep,
    create_request,
    create_room,
    create_vendor,
    get_success_data,
    is_valid_uuid,
    make_nurse_headers,
    make_scheduler_headers,
    make_tech_headers,
    make_vendor_rep_headers,
    rep_headers,
    set_clock,
    setup_approved_request,
    submit_request,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.factories import (
    check_in_line,
    create_access_pass_payload,
    create_check_in_payload,
    create_tray_payload,
    create_vendor_payload,
    decide_request_payload,
    verify_check_in_payload,
    line_disposition,
)

SCHEDULER = make_scheduler_headers()
TECH = make_tech_headers()
NURSE = make_nurse_headers()


class TestAuthContext:
    def test_missing_auth_headers_returns_400(self, api):
        """PRD: "All interactions with the API must be authenticated through
        two mandatory HTTP headers: `X-User-ID`, identifying the acting user,
        and `X-User-Role`, naming their operational capacity. A request
        missing either header, or carrying an empty value in either, is
        rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP
        400)."

        Design: Corner/validations/missing_auth_headers_returns_400
        """
        create_room()
        resp = api.create_vendor(create_vendor_payload(), None)
        validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)
        _rows, meta = validate_paginated(api.list_vendors(coordinator()))
        assert meta["total_count"] == 0, "no vendor may be persisted"

    def test_role_forbidden_returns_403(self, api):
        """PRD: "Beyond authentication, each operation is restricted to
        designated roles; an authenticated caller whose role is not on an
        operation's authorized list is rejected with `ERR_FORBIDDEN_ROLE`
        (HTTP 403)."

        Design: Corner/validations/role_forbidden_returns_403
        """
        create_room()
        resp = api.create_vendor(
            create_vendor_payload(),
            make_vendor_rep_headers(NON_EXISTENT_UUID))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)
        _rows, meta = validate_paginated(api.list_vendors(coordinator()))
        assert meta["total_count"] == 0


class TestValidationPrecedence:
    def test_body_shape_precedes_existence(self, api):
        """PRD: "When several rules could reject the same request, the server
        evaluates them in a fixed global order, and the caller receives the
        error from the first failing tier."
        PRD: "**Body well-formedness** — the request body parses, contains every
        required field, and every field has a valid type and, where
        enumerated, a valid enum member, else `ERR_VALIDATION` (400)."

        Design: Corner/validations/body_shape_precedes_existence
        """
        # Missing tray_code AND a non-existent request id: the body-shape
        # tier runs before the existence tier.
        resp = api.add_tray(
            NON_EXISTENT_UUID,
            {"declared_instrument_count": 5, "replacement_value_cents": 1000},
            SCHEDULER)
        validate_error(resp, ApiErrorId.ERR_VALIDATION)

    def test_existence_check_valid_path_bogus_id_returns_404(self, api):
        """PRD: "**Existence** — every referenced resource exists, validated
        left-to-right, else the matching `ERR_{RESOURCE}_NOT_FOUND` (404)."

        Design: Corner/validations/existence_check_valid_path_bogus_id_returns_404
        """
        resp = api.add_tray(
            NON_EXISTENT_UUID,
            create_tray_payload(declared_instrument_count=5,
                                replacement_value_cents=1000),
            SCHEDULER)
        validate_error(resp, ApiErrorId.ERR_REQUEST_NOT_FOUND)


class TestNotFound:
    def test_get_tray_not_found_returns_404(self, api):
        """PRD: "For any request whose path chains identifiers, the server
        validates existence strictly left-to-right in path-template order and
        rejects with the `404` error of the first identifier that does not
        resolve — `ERR_VENDOR_NOT_FOUND`, `ERR_CASE_NOT_FOUND`,
        `ERR_REQUEST_NOT_FOUND`, `ERR_TRAY_NOT_FOUND`, `ERR_CHECKIN_NOT_FOUND`,
        `ERR_TURN_NOT_FOUND`, `ERR_ESCALATION_NOT_FOUND`, `ERR_PASS_NOT_FOUND`,
        `ERR_PICKUP_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`, `ERR_PENALTY_NOT_FOUND`,
        `ERR_DELAY_EVENT_NOT_FOUND`, `ERR_REP_NOT_FOUND`, `ERR_ROOM_NOT_FOUND`,
        or `ERR_STERILIZER_NOT_FOUND` — before examining anything further down
        the chain."

        Design: Corner/entities/get_tray_not_found_returns_404
        """
        create_room()
        resp = api.get_tray(NON_EXISTENT_UUID, coordinator())
        validate_error(resp, ApiErrorId.ERR_TRAY_NOT_FOUND)
        assert resp.status_code == 404

    @pytest.mark.parametrize("method_name,error_id", [
        ("get_vendor", "ERR_VENDOR_NOT_FOUND"),
        ("get_rep", "ERR_REP_NOT_FOUND"),
        ("get_or_room", "ERR_ROOM_NOT_FOUND"),
        ("get_sterilizer_unit", "ERR_STERILIZER_NOT_FOUND"),
        ("get_case", "ERR_CASE_NOT_FOUND"),
        ("get_request", "ERR_REQUEST_NOT_FOUND"),
        ("get_check_in", "ERR_CHECKIN_NOT_FOUND"),
        ("get_turn", "ERR_TURN_NOT_FOUND"),
        ("get_escalation", "ERR_ESCALATION_NOT_FOUND"),
        ("get_access_pass", "ERR_PASS_NOT_FOUND"),
        ("get_pickup", "ERR_PICKUP_NOT_FOUND"),
        ("get_claim", "ERR_CLAIM_NOT_FOUND"),
        ("get_penalty", "ERR_PENALTY_NOT_FOUND"),
        ("get_delay_event", "ERR_DELAY_EVENT_NOT_FOUND"),
    ])
    def test_get_single_not_found_family_returns_404(self, api, method_name,
                                                     error_id):
        """PRD: "For any request whose path chains identifiers, the server
        validates existence strictly left-to-right in path-template order and
        rejects with the `404` error of the first identifier that does not
        resolve — `ERR_VENDOR_NOT_FOUND`, `ERR_CASE_NOT_FOUND`,
        `ERR_REQUEST_NOT_FOUND`, `ERR_TRAY_NOT_FOUND`, `ERR_CHECKIN_NOT_FOUND`,
        `ERR_TURN_NOT_FOUND`, `ERR_ESCALATION_NOT_FOUND`, `ERR_PASS_NOT_FOUND`,
        `ERR_PICKUP_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`, `ERR_PENALTY_NOT_FOUND`,
        `ERR_DELAY_EVENT_NOT_FOUND`, `ERR_REP_NOT_FOUND`, `ERR_ROOM_NOT_FOUND`,
        or `ERR_STERILIZER_NOT_FOUND` — before examining anything further down
        the chain."

        Design: Corner/entities/get_single_not_found_family_returns_404
        """
        resp = getattr(api, method_name)(NON_EXISTENT_UUID, coordinator())
        validate_error(resp, getattr(ApiErrorId, error_id))
        assert resp.status_code == 404


class TestErrorEnvelope:
    def test_error_envelope_shape_on_404(self, api):
        """PRD: "The `meta` object for error responses contains only
        `api_request_id` and `api_request_timestamp`."
        PRD: "The `error_id` is a unique, machine-readable string that
        identifies the specific error."
        PRD: "The `message` provides a human-readable explanation of what
        went wrong."

        Design: Corner/errors/error_envelope_shape_on_404
        """
        resp = api.get_case(NON_EXISTENT_UUID, coordinator())
        error = validate_error(resp, ApiErrorId.ERR_CASE_NOT_FOUND)
        body = resp.json()
        assert body["response_type"] == "error"
        assert isinstance(error["message"], str) and error["message"].strip()
        meta = body["meta"]
        assert isinstance(meta.get("api_request_id"), str) \
            and meta["api_request_id"]
        assert isinstance(meta.get("api_request_timestamp"), str) \
            and meta["api_request_timestamp"]


class TestRoleBoundaries:
    def test_vendor_rep_cannot_verify_checkin(self, api):
        """PRD: "Beyond authentication, each operation is restricted to
        designated roles; an authenticated caller whose role is not on an
        operation's authorized list is rejected with `ERR_FORBIDDEN_ROLE`
        (HTTP 403)."
        PRD: "Verification is the coordinator's counterpart, expressed as
        `line_dispositions` — one disposition per line, each either `ACCEPT`
        or `QUARANTINE`."

        Design: Corner/rbac/vendor_rep_cannot_verify_checkin
        """
        world = setup_approved_request()
        tray = world["trays"][0]
        ci = get_success_data(
            api.create_check_in(
                world["request"]["id"],
                create_check_in_payload(
                    [check_in_line(tray["id"], 50)]),
                rep_headers(world["rep"])), 201)

        resp = api.verify_check_in(
            ci["id"],
            verify_check_in_payload([line_disposition(tray["id"], "ACCEPT")]),
            rep_headers(world["rep"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)
        assert validate_success(
            api.get_check_in(ci["id"], coordinator()))["status"] == "SUBMITTED"

    def test_scheduler_cannot_decide_request(self, api):
        """PRD: "Beyond authentication, each operation is restricted to
        designated roles; an authenticated caller whose role is not on an
        operation's authorized list is rejected with `ERR_FORBIDDEN_ROLE`
        (HTTP 403)."
        PRD: "Decision belongs to the `VendorCoordinator` and is expressed
        through a `decision` payload — `APPROVE` or `REJECT` — with an
        optional `reason`."

        Design: Corner/rbac/scheduler_cannot_decide_request
        """
        vendor = create_vendor()
        room = create_room()
        case = create_case(room["id"], case_number="C-1",
                           scheduled_start_at="2026-08-10T09:00:00Z",
                           scheduled_end_at="2026-08-10T12:00:00Z")
        request = create_request(case["id"], vendor["id"], "STANDARD")
        add_tray(request["id"], tray_code="TK-1", declared_instrument_count=5,
                 replacement_value_cents=1000)
        submit_request(request["id"])

        resp = api.decide_request(request["id"],
                                  decide_request_payload("APPROVE"),
                                  SCHEDULER)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)
        assert validate_success(
            api.get_request(request["id"], coordinator()))["status"] == "SUBMITTED"

    def test_vendor_rep_cannot_request_pass_for_another_rep(self, api):
        """PRD: "a `VendorRep` caller may only request a pass for themselves,
        so the payload's `rep_id` must equal the caller's `X-User-ID` —
        anything else is `ERR_REP_VENDOR_MISMATCH` (403) — while a
        `VendorCoordinator` may file for any rep."

        Design: Corner/rbac/vendor_rep_cannot_request_pass_for_another_rep
        """
        vendor = create_vendor()
        rep1 = create_rep(vendor["id"], full_name="Rita Rep",
                          rep_email="r@acme.com", credential_doc_ref="DOC-1")
        rep2 = create_rep(vendor["id"], full_name="Ron Rep",
                          rep_email="ron@acme.com", credential_doc_ref="DOC-2")
        room = create_room()
        case = create_case(room["id"], case_number="C-1")

        resp = api.create_access_pass(
            create_access_pass_payload(rep2["id"], case["id"]),
            rep_headers(rep1))
        validate_error(resp, ApiErrorId.ERR_REP_VENDOR_MISMATCH)
        _rows, meta = validate_paginated(
            api.list_access_passes(coordinator(),
                                   params={"case_id": case["id"]}))
        assert meta["total_count"] == 0

    def test_any_role_can_read(self, api):
        """PRD: "A sixth pseudo-role, `Any`, denotes that every authenticated
        role may use the read operations; all list and single-resource
        retrieval endpoints are available to any of the five roles above."

        Design: Corner/rbac/any_role_can_read
        """
        vendor = create_vendor()
        rep = create_rep(vendor["id"])
        room = create_room()
        case = create_case(room["id"], case_number="C-1")

        for headers in (coordinator(), SCHEDULER, TECH, NURSE,
                        make_vendor_rep_headers(rep["id"])):
            fetched = validate_success(api.get_case(case["id"], headers))
            assert fetched["status"] == "SCHEDULED"
            assert is_valid_uuid(fetched["id"])


class TestExpiredCredentialCheckIn:
    """Difficulty instance: an EXPIRED-credential rep whose count sheet also
    names a foreign tray fails the credentialing-safety tier (7) before the
    referential-coherence tier (10)."""

    def _two_request_world(self, api):
        """Vendor ACME, rep credentialed until 2026-08-04T00:00:00Z; two
        APPROVED STANDARD requests (trays t1/t2) on the 2026-08-05 case;
        clock advanced to exactly the expiry instant."""
        vendor = create_vendor()
        rep = create_credentialed_rep(vendor["id"],
                                      expires="2026-08-04T00:00:00Z")
        room = create_room()
        case = create_case(room["id"], case_number="C-1001",
                           scheduled_start_at="2026-08-05T09:00:00Z",
                           scheduled_end_at="2026-08-05T12:00:00Z")
        requests = []
        for code, declared, value in (("TK-1", 50, 300000),
                                      ("TK-9", 10, 50000)):
            rq = create_request(case["id"], vendor["id"], "STANDARD")
            tray = add_tray(rq["id"], tray_code=code,
                            declared_instrument_count=declared,
                            replacement_value_cents=value)
            submit_request(rq["id"])
            approve_request(rq["id"])
            requests.append((rq, tray))
        set_clock("2026-08-04T00:00:00Z")
        swept = validate_success(api.get_rep(rep["id"], coordinator()))
        assert swept["credential_status"] == "EXPIRED", \
            "the sweep expires a credential whose expiry has been reached"
        return vendor, rep, case, requests

    def test_checkin_expired_credential_reports_safety_error(self, api):
        """PRD: "When several rules could reject the same request, the server
        evaluates them in a fixed global order, and the caller receives the
        error from the first failing tier."
        PRD: "**Credentialing and sterility safety** — an acting rep's credential
        is `ACTIVE` and the rep belongs to the vendor being acted for; an
        implant tray is never checked in without its implant log;
        decontamination minimums and cooldowns have elapsed; a credential
        outlives the case it supports. These raise
        `ERR_REP_CREDENTIAL_NOT_ACTIVE` (409), `ERR_IMPLANT_LOG_REQUIRED`
        (422), `ERR_DECON_MIN_NOT_ELAPSED` (409), `ERR_COOLDOWN_NOT_ELAPSED`
        (409), or `ERR_CREDENTIAL_WINDOW_INSUFFICIENT` (409)."
        PRD: "**Cross-entity referential coherence** — the acting rep belongs to
        the request's or claim's vendor, line trays belong to the path
        request, a delay event's linked request belongs to the case, a claim's
        tray and request agree, and an escalation's linked tray belongs to its
        request, raising `ERR_REP_VENDOR_MISMATCH` (403),
        `ERR_TRAY_NOT_IN_REQUEST` (422), `ERR_DELAY_REQUEST_LINK` (422), or
        `ERR_DELAY_EVENT_INVALID` (422)."

        Design: Difficulty/priority_pair_validation_conflict/checkin_expired_credential_safety_beats_tray_mismatch_referential
        """
        _vendor, rep, _case, requests = self._two_request_world(api)
        (rq1, t1), (rq2, _t2) = requests
        # The line names rq1's tray (referential failure) AND the rep's
        # credential is EXPIRED (safety failure): safety answers first.
        resp = api.create_check_in(
            rq2["id"],
            create_check_in_payload(
                [check_in_line(t1["id"], 50)], loaner_agreement_ref="LA-9"),
            rep_headers(rep))
        validate_error(resp, ApiErrorId.ERR_REP_CREDENTIAL_NOT_ACTIVE)

    def test_checkin_expired_credential_persists_nothing(self, api):
        """PRD: "A rep whose credential is not `ACTIVE` may not perform
        vendor-side delivery or pickup actions — such attempts fail with
        `ERR_REP_CREDENTIAL_NOT_ACTIVE` (409)"

        Design: Difficulty/priority_pair_validation_conflict/checkin_expired_credential_safety_beats_tray_mismatch_referential
        """
        _vendor, rep, _case, requests = self._two_request_world(api)
        (rq1, t1), (rq2, _t2) = requests
        resp = api.create_check_in(
            rq2["id"],
            create_check_in_payload(
                [check_in_line(t1["id"], 50)], loaner_agreement_ref="LA-9"),
            rep_headers(rep))
        validate_error(resp, ApiErrorId.ERR_REP_CREDENTIAL_NOT_ACTIVE)

        _rows, meta = validate_paginated(
            api.list_check_ins(coordinator(), params={"request_id": rq2["id"]}))
        assert meta["total_count"] == 0, "no CheckInEvent may be persisted"
        request_after = validate_success(api.get_request(rq2["id"],
                                                         coordinator()))
        assert request_after["status"] == "APPROVED"
