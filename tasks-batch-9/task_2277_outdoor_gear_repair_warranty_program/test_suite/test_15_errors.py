"""Authentication, role recognition, actor resolution and error-envelope shape.

The first three checks of the PRD §2.11 gauntlet run before anything else this
API does: headers must be present, the role name must be recognised, and an
entity-backed role's `X-User-ID` must resolve. Each test below sends a request
that breaks several rules at once and pins the earliest answer, then checks the
rejection envelope carries nothing but `error_id` and `message`.
"""

from test_helpers import (
    ERR_CLAIM_NOT_FOUND,
    ERR_INVALID_CLAIM_STATE,
    ERR_INVALID_PAGINATION,
    ERR_INVALID_ROLE,
    ERR_MISSING_AUTH_HEADERS,
    ERR_UNKNOWN_ACTOR,
    PROGRAM_ADMIN_HEADERS,
    PROGRAM_ADMIN_ID,
    ROLE_CUSTOMER,
    ROLE_PROGRAM_ADMIN,
    ROLE_REPAIR_TECHNICIAN,
    ROLE_SERVICE_AGENT,
    SERVICE_AGENT_HEADERS,
    factories,
    headers_with_blank_role,
    headers_without_role,
    headers_without_user_id,
    is_iso8601_timestamp,
    make_headers,
    validate_error,
    validate_success,
)

# Identifiers that resolve to nothing at all.
UNKNOWN_CENTER_ID = "00000000-0000-4000-8000-0000000009ff"
UNKNOWN_CLAIM_ID = "00000000-0000-4000-8000-0000000007ff"
UNKNOWN_ACTOR_ID = "00000000-0000-4000-8000-0000000008ff"

# A syntactically well-formed header value that is not one of the five roles.
UNRECOGNISED_ROLE = "GearWizard"


def _assert_error_envelope(response, expected_error_id):
    """Assert the PRD §2.2 error envelope and return the parsed body."""
    validate_error(response, expected_error_id)
    body = response.json()
    assert body["response_type"] == "error", body
    assert set(body["data"]) == {"error_id", "message"}, body["data"]
    assert set(body["meta"]) == {"api_request_id", "api_request_timestamp"}, body["meta"]
    assert body["meta"]["api_request_id"].startswith("req_"), body["meta"]
    assert is_iso8601_timestamp(body["meta"]["api_request_timestamp"]), body["meta"]
    return body


class TestMissingAuthHeaders:
    """PRD §2.11 check 1 — the gauntlet's first gate."""

    def test_absent_or_blank_auth_headers_are_unauthenticated(self, api, scenario):
        """A header that is absent or blank is 401, never a 200 read.

        "Every request to this API must carry two headers: `X-User-ID`,
        identifying the acting principal, and `X-User-Role`, naming the role
        that principal is acting in."
        "If either header is absent or blank, the request is rejected with
        `ERR_MISSING_AUTH_HEADERS` (HTTP 401)."
        "Every request runs the same ordered gauntlet, and the **first** check
        that fails produces the response — no later check is evaluated, so a
        request that violates several rules always reports the earliest one."

        Design: Corner/errors/missing_auth_headers_returns_unauthenticated
        """
        scenario.set_clock()
        center = scenario.center()

        variants = {
            "no headers at all": {},
            "blank X-User-ID": make_headers(ROLE_SERVICE_AGENT, ""),
            "X-User-Role absent": headers_without_role(),
            "X-User-ID absent": headers_without_user_id(),
            "blank X-User-Role": headers_with_blank_role(),
        }
        for label, headers in variants.items():
            response = api.get_service_center(center["id"], headers)
            assert response.status_code == 401, f"{label}: {response.text}"
            _assert_error_envelope(response, ERR_MISSING_AUTH_HEADERS)

        # The control read with both headers present proves the row is readable.
        readable = validate_success(
            api.get_service_center(center["id"], SERVICE_AGENT_HEADERS)
        )
        assert readable["id"] == center["id"], readable

    def test_headerless_write_leaves_the_centre_untouched(self, api, scenario):
        """A headerless mutating call is refused before it can touch the centre.

        "If either header is absent or blank, the request is rejected with
        `ERR_MISSING_AUTH_HEADERS` (HTTP 401)."
        "A freshly registered centre starts with `open_liability_cents` at 0,
        `liability_utilization_pct` at 0, `liability_posture` at `OPEN`,
        `active_queue_depth` at 0 and `current_surge_multiplier` at 1.0; its
        `breached_commitment_count` is 0 and its `last_queue_review_at` is null
        until the first checkpoint runs."
        "Almost every resource additionally carries `updated_at`, an ISO 8601
        UTC timestamp refreshed on every mutation, and `version`, an integer
        that starts at 1 and increments by one on every mutation of that row."

        Design: Corner/errors/missing_auth_headers_returns_unauthenticated
        """
        scenario.set_clock()
        center = scenario.center()

        _assert_error_envelope(
            api.queue_review(center["id"], {}), ERR_MISSING_AUTH_HEADERS
        )

        after = validate_success(
            api.get_service_center(center["id"], PROGRAM_ADMIN_HEADERS)
        )
        assert after["version"] == center["version"], after
        assert after["open_liability_cents"] == 0, after
        assert after["last_queue_review_at"] is None, after


class TestUnrecognizedRoleHeader:
    """PRD §2.11 check 2 — role recognition outranks every later check."""

    def test_unknown_role_answers_invalid_role_even_for_a_missing_path_id(
        self, api, scenario
    ):
        """An unrecognised role never reveals whether the addressed id exists.

        "If `X-User-Role` is present but is not one of the five recognised role
        names — `Customer`, `ServiceAgent`, `RepairTechnician`,
        `PartsCoordinator`, `ProgramAdmin` — the request is rejected with
        `ERR_INVALID_ROLE` (HTTP 401)."
        "Every request runs the same ordered gauntlet, and the **first** check
        that fails produces the response — no later check is evaluated, so a
        request that violates several rules always reports the earliest one."
        "Every identifier in the URL path resolves, validated left to right, so
        that the leftmost unresolvable segment is the one reported."

        Design: Corner/errors/unrecognized_role_header_is_invalid_role_before_any_lookup
        """
        scenario.set_clock()
        center = scenario.center()
        wizard = make_headers(UNRECOGNISED_ROLE, PROGRAM_ADMIN_ID)

        _assert_error_envelope(
            api.get_service_center(center["id"], wizard), ERR_INVALID_ROLE
        )
        # The centre id here resolves to nothing, yet check 2 still owns the answer.
        _assert_error_envelope(
            api.get_service_center(UNKNOWN_CENTER_ID, wizard), ERR_INVALID_ROLE
        )

        control = validate_success(
            api.get_service_center(center["id"], SERVICE_AGENT_HEADERS)
        )
        assert control["id"] == center["id"], control

    def test_unknown_role_outranks_the_role_list_and_the_input_schema(
        self, api, scenario
    ):
        """An unrecognised role beats both the permitted-role list and the schema.

        "If `X-User-Role` is present but is not one of the five recognised role
        names — `Customer`, `ServiceAgent`, `RepairTechnician`,
        `PartsCoordinator`, `ProgramAdmin` — the request is rejected with
        `ERR_INVALID_ROLE` (HTTP 401)."
        "Every request runs the same ordered gauntlet, and the **first** check
        that fails produces the response — no later check is evaluated, so a
        request that violates several rules always reports the earliest one."

        Design: Corner/errors/unrecognized_role_header_is_invalid_role_before_any_lookup
        """
        scenario.set_clock()
        wizard = make_headers(UNRECOGNISED_ROLE, PROGRAM_ADMIN_ID)

        # Centre registration is a ProgramAdmin operation and this body has no
        # `name` at all, so checks 4 and 9 would both fail after check 2.
        _assert_error_envelope(
            api.create_service_center(
                factories.service_center_payload(
                    name=factories.OMIT, liability_cap_cents=0
                ),
                wizard,
            ),
            ERR_INVALID_ROLE,
        )
        # Adjudication is a ServiceAgent / ProgramAdmin operation and the claim
        # id resolves to nothing, so checks 4 and 6 would both fail as well.
        _assert_error_envelope(
            api.decide_claim(UNKNOWN_CLAIM_ID, wizard, {}), ERR_INVALID_ROLE
        )


class TestUnknownActorForEntityBackedRoles:
    """PRD §2.11 check 3 — the two entity-backed roles must resolve."""

    def test_unresolvable_actor_id_is_rejected_only_for_entity_backed_roles(
        self, api, scenario
    ):
        """A Customer or RepairTechnician id must resolve; opaque roles skip it.

        "When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting
        Customer row; ownership checks on any resource that references a
        Customer compare the resource's owner reference to `X-User-ID`."
        "In either case, if `X-User-ID` does not resolve to an existing row of
        the backing entity, the request is rejected with `ERR_UNKNOWN_ACTOR`
        (HTTP 401)."
        "The same holds when `X-User-Role` is `PartsCoordinator` and when
        `X-User-Role` is `ProgramAdmin`: both are opaque operator identifiers,
        not rows, and no ownership comparison is ever performed against them."

        Design: Corner/errors/unknown_actor_id_rejected_for_entity_backed_roles
        """
        scenario.set_clock()
        center = scenario.center()
        customer = scenario.customer()

        _assert_error_envelope(
            api.get_customer(customer["id"], make_headers(ROLE_CUSTOMER, UNKNOWN_ACTOR_ID)),
            ERR_UNKNOWN_ACTOR,
        )
        # The id resolves — but to a Customer, and RepairTechnician is backed by
        # the Technician entity, of which no row exists at all.
        _assert_error_envelope(
            api.list_technicians(
                make_headers(ROLE_REPAIR_TECHNICIAN, customer["id"]),
                service_center_id=center["id"],
            ),
            ERR_UNKNOWN_ACTOR,
        )

        opaque = validate_success(
            api.get_customer(
                customer["id"], make_headers(ROLE_PROGRAM_ADMIN, UNKNOWN_ACTOR_ID)
            )
        )
        assert opaque["full_name"] == "Rowan Ives", opaque

    def test_unresolvable_actor_id_outranks_the_permitted_role_list(
        self, api, scenario
    ):
        """Actor resolution answers before the endpoint's role list is consulted.

        "In either case, if `X-User-ID` does not resolve to an existing row of
        the backing entity, the request is rejected with `ERR_UNKNOWN_ACTOR`
        (HTTP 401)."
        "Role capability is per endpoint."
        "Every request runs the same ordered gauntlet, and the **first** check
        that fails produces the response — no later check is evaluated, so a
        request that violates several rules always reports the earliest one."

        Design: Corner/errors/unknown_actor_id_rejected_for_entity_backed_roles
        """
        scenario.set_clock()

        # Centre registration and catalogue creation are ProgramAdmin-only, so
        # check 4 would refuse both of these callers had check 3 let them past.
        _assert_error_envelope(
            api.create_service_center(
                factories.service_center_payload(),
                make_headers(ROLE_REPAIR_TECHNICIAN, UNKNOWN_ACTOR_ID),
            ),
            ERR_UNKNOWN_ACTOR,
        )
        _assert_error_envelope(
            api.create_gear_model(
                factories.gear_model_payload(),
                make_headers(ROLE_CUSTOMER, UNKNOWN_ACTOR_ID),
            ),
            ERR_UNKNOWN_ACTOR,
        )


class TestErrorEnvelopeShape:
    """PRD §2.2 — one envelope for every rejection, whatever its status."""

    def test_every_rejection_carries_the_same_error_envelope(self, api, scenario):
        """401, 404, 409 and 422 all answer with error_id and message only.

        "The `meta` object for error responses contains only `api_request_id`
        and `api_request_timestamp`."
        "The `error_id` is a unique, machine-readable string that identifies
        the specific error."
        "The `message` provides a human-readable explanation of what went
        wrong."
        "The `api_request_id` is a server-generated unique identifier for the
        request that starts with `req_`."
        "A `limit` below 1 or above 100, or a negative `offset`, is rejected
        with `ERR_INVALID_PAGINATION` (HTTP 422)."
        "The identifier-specific codes are `ERR_SERVICE_CENTER_NOT_FOUND`,
        `ERR_GEAR_MODEL_NOT_FOUND`, `ERR_CUSTOMER_NOT_FOUND`,
        `ERR_GEAR_ITEM_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`,
        `ERR_ASSESSMENT_NOT_FOUND`, `ERR_TECHNICIAN_NOT_FOUND`,
        `ERR_REPAIR_ORDER_NOT_FOUND`, `ERR_ESTIMATE_NOT_FOUND`,
        `ERR_PART_LOT_NOT_FOUND`, `ERR_RESERVATION_NOT_FOUND` and
        `ERR_WORK_BLOCK_NOT_FOUND`, all HTTP 404."
        "Resubmitting closes the loop, moving `INFO_REQUESTED` → `SUBMITTED`,
        and is available to the owner or to a `ServiceAgent`; a `Customer`
        caller must again own the unit."
        "At creation the claim's `status` is `DRAFT`, its `info_request_count`
        and `assessment_count` are both 0, its `submitted_at`,
        `latest_determination`, `latest_repair_cost_cents`, `decision`,
        `decision_threshold_pct`, `repair_ratio_pct`, `decision_by_role` and
        `decided_at` are all null, and its `proof_verified` flag is derived
        from the unit: it is true exactly when the unit's
        `proof_of_purchase_type` is not `NONE` and its `proof_of_purchase_ref`
        is not null, and it is recomputed whenever those fields change."

        Design: Corner/errors/error_envelope_shape_is_uniform_across_rejected_requests
        """
        scenario.set_clock()
        center = scenario.center()
        model = scenario.model()
        customer = scenario.customer()
        item = scenario.gear_item(model["id"], customer["id"])
        claim = scenario.claim(center["id"], item["id"])

        pagination = api.list_warranty_claims(SERVICE_AGENT_HEADERS, limit=0)
        assert pagination.status_code == 422, pagination.text
        _assert_error_envelope(pagination, ERR_INVALID_PAGINATION)

        missing = api.get_warranty_claim(UNKNOWN_CLAIM_ID, SERVICE_AGENT_HEADERS)
        assert missing.status_code == 404, missing.text
        _assert_error_envelope(missing, ERR_CLAIM_NOT_FOUND)

        # Resubmit is legal only from INFO_REQUESTED; this claim is still DRAFT.
        wrong_state = api.resubmit_claim(
            claim["id"], {"customer_narrative": "Adding photos."}, SERVICE_AGENT_HEADERS
        )
        assert wrong_state.status_code == 409, wrong_state.text
        conflict = _assert_error_envelope(wrong_state, ERR_INVALID_CLAIM_STATE)
        assert "status" not in conflict["data"], conflict
        assert "version" not in conflict["data"], conflict

        unauthenticated = api.get_warranty_claim(
            claim["id"], make_headers(UNRECOGNISED_ROLE, PROGRAM_ADMIN_ID)
        )
        assert unauthenticated.status_code == 401, unauthenticated.text
        _assert_error_envelope(unauthenticated, ERR_INVALID_ROLE)

        unchanged = scenario.read_claim(claim["id"])
        assert unchanged["status"] == "DRAFT", unchanged
        assert unchanged["info_request_count"] == 0, unchanged
