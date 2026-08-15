"""Hangar inventory creation rules, envelope/pagination, nested listing, and auth headers."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    add_hangar,
    add_rate_schedule,
    api_client,
    assert_hangar,
    create_airport,
    create_hangar_payload,
    create_inspection_payload,
    make_applicant_headers,
    setup_lease,
    submit_application,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_hangar_creation_missing_required_size_class_rejected(api, manager_headers):
    """PRD §3.1: "malformed creation payloads — a missing required field, an invalid enum spelling, or a non-positive value where a positive one is required — are rejected with `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/entities/hangar_creation_missing_required_size_class_returns_invalid_request
    """
    airport = create_airport(airport_code="KREQ")
    payload = create_hangar_payload(airport_id=airport["id"], hangar_code="T-99",
                                    door_type="SLIDING")
    del payload["size_class"]
    resp = api.create_hangar(payload, manager_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_hangar_invalid_size_class_enum_rejected(api, manager_headers):
    """PRD §3.1: "malformed creation payloads — a missing required field, an invalid enum spelling, or a non-positive value where a positive one is required — are rejected with `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/entities/hangar_invalid_size_class_enum_rejected
    """
    airport = create_airport(airport_code="KENM")
    resp = api.create_hangar(
        create_hangar_payload(airport_id=airport["id"], hangar_code="T-98",
                              size_class="MEGA", door_type="SLIDING"),
        manager_headers,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_get_hangar_nonexistent_returns_not_found(api, manager_headers):
    """PRD §2.10: "Endpoints that address a resource nested under others validate every path identifier left to right — the airport first, then the hangar, application, lease, or offer, then the child resource — and each `{id}` segment must identify an existing resource. A failure at any segment is rejected with `ERR_NOT_FOUND` (HTTP 404)."

    Design: Corner/entities/get_hangar_nonexistent_returns_not_found
    """
    create_airport(airport_code="KNF")
    resp = api.get_hangar(NON_EXISTENT_UUID, manager_headers)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


def test_hangar_list_pagination_envelope(api, manager_headers):
    """PRD §2.3: "Every list endpoint accepts the query parameters `limit` and `offset`. The `limit` parameter defaults to 10, with a minimum of 1 and a maximum of 100; `offset` defaults to 0. List responses are sorted by `created_at` ascending. The `meta` object of a list response carries the pagination fields `limit`, `offset`, `total_count`, and `has_more`."
    PRD §2.2: "The `response_type` is either "object" for a single resource or "array" for a list of resources."

    Design: Corner/entities/hangar_list_pagination_envelope
    """
    airport = create_airport(airport_code="KPG")
    add_hangar(airport["id"], hangar_code="T-1", size_class="T_HANGAR")
    add_hangar(airport["id"], hangar_code="T-2", size_class="T_HANGAR")
    add_hangar(airport["id"], hangar_code="B-1", size_class="BOX", door_type="BIFOLD")

    resp1 = api.list_hangars(manager_headers, params={"limit": 2, "offset": 0})
    assert resp1.json().get("response_type") == "array", "list responses must carry response_type array"
    assert str(resp1.json().get("meta", {}).get("api_request_id", "")).startswith("req_"), (
        "envelope meta must carry api_request_id starting with req_"
    )
    page1, meta1 = validate_paginated(resp1)
    assert len(page1) == 2 and meta1["total_count"] == 3 and meta1["has_more"] is True, (
        f"page 1 must hold 2 of 3 rows with has_more true, got {meta1}"
    )

    resp2 = api.list_hangars(manager_headers, params={"limit": 2, "offset": 2})
    page2, meta2 = validate_paginated(resp2)
    assert len(page2) == 1 and meta2["has_more"] is False, (
        f"page 2 must hold the final row with has_more false, got {meta2}"
    )


def test_hangar_creation_sets_system_posture_and_condition(api, manager_headers):
    """PRD §3.1: "A new hangar starts with `condition_rating` `GOOD`, `posture` `AVAILABLE`, and `status` `OPERATIONAL`."

    Design: Corner/entities/hangar_computed_posture_ignores_client_input
    """
    airport = create_airport(airport_code="KCMP")
    hangar = add_hangar(airport["id"], hangar_code="T-77", size_class="T_HANGAR")
    assert_hangar(hangar)
    assert hangar["posture"] == "AVAILABLE"
    assert hangar["condition_rating"] == "GOOD"
    assert hangar["status"] == "OPERATIONAL"


def test_inspection_close_updates_hangar_condition_and_posture(api, manager_headers,
                                                               compliance_headers):
    """PRD §3.6: "On close the inspection becomes `CLOSED`, the hangar's `condition_rating` adopts this inspection's rating — the latest `CLOSED` inspection always wins — the hangar's `version` increments, and its `posture` is recomputed under the compound rule of §2.8."
    PRD §2.8: "`MAINTENANCE_HOLD`: no such lease exists and `condition_rating` is `OUT_OF_SERVICE`."
    PRD §3.6: "When `maintenance_responsibility` is `TENANT` and the rating is `POOR` or `OUT_OF_SERVICE`, a `remediation_note` attesting the remediation must accompany the close (`ERR_REMEDIATION_NOTE_REQUIRED`, HTTP 422)."

    Design: Corner/state_machines/inspection_close_updates_hangar_condition_and_posture
    """
    airport = create_airport(airport_code="KINS")
    add_rate_schedule(airport["id"], size_class="T_HANGAR", monthly_rate_cents=90000)
    vacant = add_hangar(airport["id"], hangar_code="T-80", size_class="T_HANGAR")
    ctx = setup_lease(airport_overrides={"airport_code": "KIN2"}, size_class="T_HANGAR",
                      rate=90000, hangar_code="T-81")
    leased_hangar = ctx["hangar"]

    insp1 = validate_success(
        api.create_inspection(
            vacant["id"],
            create_inspection_payload(condition_rating="OUT_OF_SERVICE",
                                      maintenance_responsibility="AIRPORT",
                                      deficiency_note="Door track collapsed"),
            manager_headers,
        ),
        expected_status=201,
    )
    insp2 = validate_success(
        api.create_inspection(
            leased_hangar["id"],
            create_inspection_payload(condition_rating="POOR",
                                      maintenance_responsibility="TENANT",
                                      deficiency_note="Oil stains, wall damage"),
            compliance_headers,
        ),
        expected_status=201,
    )

    validate_success(api.close_inspection(insp1["id"], {}, manager_headers))
    hangar1 = validate_success(api.get_hangar(vacant["id"], manager_headers))
    assert hangar1["condition_rating"] == "OUT_OF_SERVICE"
    assert hangar1["posture"] == "MAINTENANCE_HOLD", (
        f"vacant OUT_OF_SERVICE hangar must be MAINTENANCE_HOLD, got {hangar1['posture']}"
    )

    resp = api.close_inspection(insp2["id"], {}, manager_headers)
    validate_error(resp, ApiErrorId.ERR_REMEDIATION_NOTE_REQUIRED)
    inspections, _ = validate_paginated(
        api.list_hangar_inspections(leased_hangar["id"], manager_headers)
    )
    assert inspections[0]["status"] == "OPEN", "rejected close must leave the inspection OPEN"


def test_filtered_list_applications_by_status(api, manager_headers):
    """PRD §4: "List endpoints accept the pagination parameters of §2.3 plus resource filters: an airport's hangars filter by `size_class` and `posture`; rate schedules by `airport_id` and `size_class`; the hangar list by `airport_id`, `size_class`, and `posture`; applications by `airport_id`, `size_class_requested`, and `status`; offers by `airport_id`, `hangar_id`, `application_id`, `rate_schedule_id`, and `status`; leases by `airport_id`, `hangar_id`, `application_id`, `offer_id`, and `status`; audit findings and rent charges by `status`; and the eviction-case list by `use_audit_finding_id` and `lease_id`."

    Design: Corner/endpoints/filtered_list_applications_by_status
    """
    airport = create_airport(airport_code="KFLT")
    app1 = submit_application(airport["id"], applicant_name="Fil One")
    app2 = submit_application(airport["id"], applicant_name="Fil Two")
    validate_success(api.withdraw_application(app2["id"], make_applicant_headers(app2["id"])))

    queued, meta_q = validate_paginated(
        api.list_applications(manager_headers,
                              params={"airport_id": airport["id"], "status": "QUEUED"})
    )
    assert [a["id"] for a in queued] == [app1["id"]] and meta_q["total_count"] == 1

    withdrawn, meta_w = validate_paginated(
        api.list_applications(manager_headers,
                              params={"airport_id": airport["id"], "status": "WITHDRAWN"})
    )
    assert [a["id"] for a in withdrawn] == [app2["id"]] and meta_w["total_count"] == 1


def test_children_listable_from_parent(api, manager_headers):
    """PRD §3.4: "On success — responded with 201 — the offer becomes `ACCEPTED`; the new lease is created in `ACTIVE` status with `tenant_name` copied from the application's `applicant_name`, `base_monthly_rate_cents` copied from the offer's `quoted_monthly_rate_cents`, `lease_start_date` set to the server timestamp, and `last_escalation_anniversary` zero; the first rent charge is created pro-rated per §3.5; the insurance certificate is created in `VALID` status; the aircraft is created `BASED` and marked primary; and the hangar's `posture` becomes `LEASED` with its `version` incremented by one."
    PRD §3.6: "The inspection opens in `OPEN` status with `inspected_at` stamped by the server and `lease_id` bound to the lease occupying the hangar at inspection time — the empty string when the hangar is vacant. Inspections are retrievable both per hangar and per lease."

    Design: Corner/endpoints/fk_reverse_reachability_children_listable_from_parent
    """
    ctx = setup_lease(airport_overrides={"airport_code": "KFK"}, size_class="T_HANGAR",
                      rate=90000, hangar_code="T-190", applicant_name="Eff Kay")
    lease = ctx["lease"]
    hangar = ctx["hangar"]
    validate_success(
        api_client.create_inspection(
            hangar["id"],
            create_inspection_payload(condition_rating="GOOD",
                                      maintenance_responsibility="AIRPORT",
                                      deficiency_note="none"),
            manager_headers,
        ),
        expected_status=201,
    )

    charges, _ = validate_paginated(api.list_rent_charges(lease["id"], manager_headers))
    assert len(charges) == 1, "activation creates exactly one (pro-rated) first charge"

    aircraft, _ = validate_paginated(api.list_aircraft(lease["id"], manager_headers))
    assert len(aircraft) == 1
    assert aircraft[0]["n_number"] == ctx["application"]["aircraft_n_number"]
    assert aircraft[0]["is_primary"] is True
    assert aircraft[0]["status"] == "BASED"

    certs, _ = validate_paginated(api.list_insurance_certificates(lease["id"], manager_headers))
    assert len(certs) == 1 and certs[0]["status"] == "VALID"

    inspections, _ = validate_paginated(api.list_hangar_inspections(hangar["id"], manager_headers))
    assert len(inspections) == 1 and inspections[0]["status"] == "OPEN"

    offers, _ = validate_paginated(
        api.list_offers(manager_headers, params={"airport_id": ctx["airport"]["id"]})
    )
    assert len(offers) == 1 and offers[0]["status"] == "ACCEPTED"

    applications, _ = validate_paginated(
        api.list_applications(manager_headers, params={"airport_id": ctx["airport"]["id"]})
    )
    assert len(applications) == 1 and applications[0]["status"] == "LEASED"


def test_missing_auth_headers_rejected(api, manager_headers):
    """PRD §2.1: "Every request must carry two headers: `X-User-ID` and `X-User-Role`. A request missing either header, or carrying a malformed value, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."

    Design: Corner/validations/missing_auth_headers_rejected
    """
    airport = create_airport(airport_code="KAU")
    resp = api.get_airport(airport["id"], headers={})
    validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)
