"""Response envelope, authentication/authorization, segregation of duties at
the QA gate, optimistic concurrency on bus version, and validation priority."""
from test_helpers import (
    ApiErrorId,
    add_labor,
    assert_bus,
    create_bus_payload,
    create_part_payload,
    create_work_order_payload,
    get_success_data,
    make_mechanic_headers,
    new_bus,
    new_mechanic,
    new_mechanic_with_certs,
    new_qa_mechanic,
    new_work_order,
    post_log,
    schedule_wo,
    setup_closed_wo_scenario,
    start_wo,
    validate_error,
    validate_success,
    wo_event,
)
from test_helpers import fixtures as fx


def test_response_envelope_success_and_error_shape(api, fleet_manager_headers):
    """PRD §2.2: "The `response_type` is either "object" for a single resource
    or "array" for a list of resources."
    PRD §2.2: "- The `api_request_id` is a server-generated unique identifier
    for the request that starts with `req_`."
    PRD §2.2: "The `error_id` is a unique, machine-readable string that
    identifies the specific error."
    PRD §2.2: "The `message` provides a human-readable explanation of what went
    wrong."

    Design: Corner/endpoints/response_envelope_success_and_error_shape
    """
    res = api.create_bus(
        create_bus_payload(fleet_number="N1", vin="VINN1",
                           initial_odometer_miles=0),
        fleet_manager_headers,
    )
    assert res.status_code == 201
    body = res.json()
    assert body["meta"]["api_request_id"], "meta.api_request_id present"
    assert body["meta"]["api_request_id"].startswith("req_")
    assert body["meta"]["api_request_timestamp"], (
        "meta.api_request_timestamp present"
    )
    assert body["response_type"] == "object"
    assert body["data"]["id"], "data carries the created resource"

    err_res = api.get_bus(
        "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2", fleet_manager_headers
    )
    assert err_res.status_code == 404
    err_body = err_res.json()
    assert err_body["response_type"] == "error"
    assert err_body["data"]["error_id"] == "ERR_NOT_FOUND"
    assert err_body["data"]["message"], "error message must be non-empty"


def test_request_without_auth_headers_unauthenticated(api):
    """PRD §2.1: "Every request to the API must carry two HTTP headers:
    `X-User-ID`, identifying the acting user, and `X-User-Role`, identifying
    the operational role. A request missing either header, or presenting a role
    the system does not recognize, is rejected with `ERR_UNAUTHENTICATED`
    (HTTP 401)."

    Design: Corner/rbac/request_without_auth_headers_unauthenticated
    """
    res = api.get_posture(headers={})
    validate_error(res, ApiErrorId.ERR_UNAUTHENTICATED)


def test_operator_cannot_create_bus_forbidden(api, operator_headers):
    """PRD §2.1: "A request whose role is not in the endpoint's authorized set
    is rejected with `ERR_FORBIDDEN` (HTTP 403)."
    PRD §4: "| POST | `/fleet/buses` | Register a bus | FleetManager |".

    Design: Corner/rbac/operator_cannot_create_bus_forbidden
    """
    res = api.create_bus(
        create_bus_payload(fleet_number="R1", vin="VINR1",
                           initial_odometer_miles=0),
        operator_headers,
    )
    validate_error(res, ApiErrorId.ERR_FORBIDDEN)


def test_mechanic_cannot_create_part_forbidden(api):
    """PRD §2.1: "A request whose role is not in the endpoint's authorized set
    is rejected with `ERR_FORBIDDEN` (HTTP 403)."
    PRD §4: "| POST | `/fleet/parts` | Create a part SKU | PartsClerk |".

    Design: Corner/rbac/mechanic_cannot_create_part_forbidden
    """
    res = api.create_part(
        create_part_payload(sku="P-R2", description="x", unit_cost_cents=100,
                            initial_on_hand=1),
        make_mechanic_headers("00000000-0000-4000-8000-0000000000bb"),
    )
    validate_error(res, ApiErrorId.ERR_FORBIDDEN)


def test_sod_qa_self_certify_rejected(api):
    """PRD §2.12: "A mechanic may not certify the quality of work they led. On
    both the certify and reject quality-assurance transitions of a work order,
    the caller's `X-User-ID` must not equal the work order's
    `lead_mechanic_id`; a violation is rejected with `ERR_SOD_QA_SELF_CERTIFY`
    (HTTP 403)."
    PRD §3.4: "A QA decision is made by a mechanic holding `QA_AUTHORITY` with
    status `VALID` or `EXPIRING_SOON` (otherwise `ERR_CERT_REQUIRED` or
    `ERR_CERT_EXPIRED`)."

    The lead also holds QA_AUTHORITY, so the cert gate passes and the SoD rule
    is the one that fires.

    Design: Corner/rbac/sod_qa_self_certify_rejected
    """
    bus = new_bus(fleet_number="R4", vin="VINR4", initial_odometer_miles=50_000,
                  base_warranty_expiry_miles=5_000,
                  base_warranty_expiry_date="2024-01-01")
    lead = new_mechanic_with_certs("QA_AUTHORITY", name="LeadQA")
    wo = new_work_order(bus["id"], lead_mechanic_id=lead["id"])
    schedule_wo(wo["id"])
    start_wo(wo["id"])
    add_labor(wo["id"], lead, hours=1)
    wo_event(wo["id"], "SUBMIT_QA", headers=make_mechanic_headers(lead["id"]))

    res = wo_event(wo["id"], "QA_CERTIFY",
                   headers=make_mechanic_headers(lead["id"]))
    validate_error(res, ApiErrorId.ERR_SOD_QA_SELF_CERTIFY)
    after = get_success_data(api.get_work_order(wo["id"], fx.SUP))
    assert after["status"] == "PENDING_QA"


def test_occ_stale_bus_version_rejected_then_fresh_succeeds(api):
    """PRD §2.9: "When creating a work order, the request must carry
    `expected_bus_version`, set to the `version` of the target `Bus` as the
    client last observed it. If the bus's `version` has since advanced —
    because, for example, another writer has opened a work order against the
    same bus or posted an odometer log that advanced the bus — the create is
    rejected with `ERR_STALE_BUS_VERSION` (HTTP 412)."
    PRD §3.7: "A successful post advances the bus. The system derives
    `miles_driven` for the log as the difference between the new
    `odometer_end` and the bus's `odometer_miles` prior to the post, then
    updates the bus's `odometer_miles` to the new `odometer_end`, recomputes
    `pm_due_status`, and increments the bus's `version`."

    Design: Corner/cross_cutting/occ_stale_bus_version_rejected_then_fresh_succeeds
    """
    bus = new_bus(fleet_number="O1", vin="VINO1", initial_odometer_miles=100,
                  base_warranty_expiry_miles=5_000,
                  base_warranty_expiry_date="2024-01-01")
    stale_version = bus["version"]
    assert stale_version == 1
    post_log(bus["id"], "2026-08-01", 700, 40)

    stale = api.create_work_order(
        create_work_order_payload(
            bus["id"], stale_version, planned_start_date="2026-08-10",
            planned_end_date="2026-08-11",
        ),
        fx.SUP,
    )
    validate_error(stale, ApiErrorId.ERR_STALE_BUS_VERSION)

    fresh = get_success_data(api.get_bus(bus["id"], fx.SUP))["version"]
    assert fresh == 2, "the log post advanced the bus version by exactly one"
    created = validate_success(
        api.create_work_order(
            create_work_order_payload(
                bus["id"], fresh, planned_start_date="2026-08-10",
                planned_end_date="2026-08-11",
            ),
            fx.SUP,
        ),
        201,
    )
    assert created["status"] == "DRAFT"


class TestTerminalStateBeatsSafety:
    """Terminal lockdown (state band) precedes the cert gate (safety band)."""

    def _closed_wo_and_uncertified_mechanic(self):
        bus, wo = setup_closed_wo_scenario(
            bus_overrides={"fleet_number": "P1", "vin": "VINP1",
                           "base_warranty_expiry_miles": 5_000,
                           "base_warranty_expiry_date": "2024-01-01"}
        )
        uncertified = new_mechanic(name="NoCert", employee_ref="E61")
        return wo, uncertified

    def test_qa_certify_on_closed_wo_reports_already_terminal(self, api):
        """PRD §2.10: "A transition attempted against a resource already in a
        terminal state is rejected with `ERR_ALREADY_TERMINAL` (HTTP 409) —
        every transition out of a terminal state is forbidden."
        PRD §2.10: "The band order is: authentication, then authorization and
        ownership, then existence of path and body references, then
        schema/format, then state-machine legality, then optimistic
        concurrency, then safety (certification, segregation-of-duties,
        safety-defect handling, on-shift dispatch), then referential
        uniqueness, then temporal windows, then business constraint, then
        fiscal."
        PRD §2.10: "In practical terms this means, for example, that a missing
        header (`ERR_UNAUTHENTICATED`) is reported before an unknown path id
        (`ERR_NOT_FOUND`), which in turn is reported before a malformed enum
        (`ERR_VALIDATION`), which is reported before an illegal state
        transition (`ERR_INVALID_STATE`), which is reported before an OCC
        stale-version rejection (`ERR_STALE_BUS_VERSION` or
        `ERR_STALE_WORK_ORDER_VERSION`), which is reported before a missing
        certification (`ERR_CERT_REQUIRED`), and so on."

        The caller holds no QA_AUTHORITY cert; state legality still fires
        first, so the outcome is ERR_ALREADY_TERMINAL, never
        ERR_CERT_REQUIRED.

        Design: Difficulty/priority_pair_validation_conflict/state_beats_safety_terminal_qa_certify
        """
        wo, uncertified = self._closed_wo_and_uncertified_mechanic()
        assert wo["status"] == "CLOSED"

        res = wo_event(wo["id"], "QA_CERTIFY",
                       headers=make_mechanic_headers(uncertified["id"]))
        validate_error(res, ApiErrorId.ERR_ALREADY_TERMINAL)
        after = get_success_data(api.get_work_order(wo["id"], fx.SUP))
        assert after["status"] == "CLOSED"

    def test_qa_reject_on_closed_wo_reports_already_terminal(self, api):
        """PRD §2.10: "A transition attempted against a resource already in a
        terminal state is rejected with `ERR_ALREADY_TERMINAL` (HTTP 409) —
        every transition out of a terminal state is forbidden."
        PRD §2.10: "A failed earlier check short-circuits the request; the
        corresponding `error_id` is what the client observes, even if a later
        check would also have failed."

        QA_REJECT is likewise a transition out of a terminal state; the missing
        QA_AUTHORITY cert (safety band) never gets evaluated.

        Design: Difficulty/priority_pair_validation_conflict/state_beats_safety_terminal_qa_certify
        """
        wo, uncertified = self._closed_wo_and_uncertified_mechanic()

        res = wo_event(wo["id"], "QA_REJECT", qa_note="reopen please",
                       headers=make_mechanic_headers(uncertified["id"]))
        validate_error(res, ApiErrorId.ERR_ALREADY_TERMINAL)
        after = get_success_data(api.get_work_order(wo["id"], fx.SUP))
        assert after["status"] == "CLOSED"
