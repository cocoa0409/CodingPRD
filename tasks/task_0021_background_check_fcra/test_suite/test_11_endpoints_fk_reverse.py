"""Sub-resource / FK reverse-reachability list endpoints: consents under an
application, orders filtered by application_id, and the at-most-one
adverse-action under an order (empty array when none exists).
"""
from test_helpers import (
    validate_success,
    set_clock, create_jurisdiction, create_applicant, create_application,
    application_in_conditional_offer, order_complete_with_results,
    make_applicant_headers, make_recruiter_headers, REC, CO,
)
from test_helpers.fixtures import api_client


def test_list_consents_under_application_returns_the_application_s_consents(api):
    """GET /api/v1/applications/{id}/consents returns the consent rows
    whose application_id is this application.

    PRD §2.5: "Several endpoints expose a sub-resource form for FK
    reverse-reachability — listing the consents under an application,
    the verifications under an order, or the (at most one) adverse-action
    under an order."

    Design: Corner/endpoints/fk_reverse_reachability_application_consents_sub_resource
    """
    set_clock("2026-06-01T10:00:00.000Z")
    jur = create_jurisdiction(state_code="UT")
    applicant = create_applicant(full_name="Vera Rubin", email="vera@example.com",
                                 date_of_birth="1928-07-23T00:00:00.000Z")
    app = create_application(applicant["id"], jur["id"], position_title="Engineer")
    consent_resp = api.create_consent(
        {"application_id": app["id"], "disclosure_text_version": "v2024-01",
         "signed_at": "2026-06-01T10:00:00.000Z", "ip_address": "1.2.3.4"},
        make_applicant_headers(applicant["id"]),
    )
    c = validate_success(consent_resp, 201)
    sub_resp = api.list_application_consents(app["id"],
                                              make_applicant_headers(applicant["id"]))
    body = sub_resp.json() if hasattr(sub_resp, "json") else sub_resp
    assert body.get("response_type") == "array", \
        f"sub-resource list must return array envelope, got {body.get('response_type')!r}"
    data = body.get("data", [])
    assert isinstance(data, list) and len(data) == 1, \
        f"expected exactly one consent under this application, got {data!r}"
    assert data[0]["id"] == c["id"], \
        f"returned consent must be the one created, got {data[0]['id']!r}"


def test_list_orders_filtered_by_application_id_returns_only_that_applications_orders(api):
    """GET /api/v1/background-check-orders?application_id=X returns only
    the orders whose application_id matches X.

    PRD §4 endpoint table: "List orders; supports filtering by
    `application_id`, `consent_id`, and `status`"

    Design: Corner/endpoints/fk_reverse_reachability_orders_filtered_by_application_id
    """
    jur, applicant, app, consent = application_in_conditional_offer(state_code="WV")
    # Create the order.
    order_resp = api.create_order(
        {"application_id": app["id"], "consent_id": consent["id"],
         "expected_application_version": app["version"]},
        make_recruiter_headers("rec-001"),
    )
    order = validate_success(order_resp, 201)
    # Now query the orders list filtered by application_id.
    listed_resp = api.list_orders(REC, params={"application_id": app["id"]})
    body = listed_resp.json() if hasattr(listed_resp, "json") else listed_resp
    assert body.get("response_type") == "array", \
        f"orders list must return array envelope, got {body.get('response_type')!r}"
    data = body.get("data", [])
    assert isinstance(data, list) and len(data) == 1, \
        f"expected exactly one order for this application, got {data!r}"
    assert data[0]["id"] == order["id"], \
        f"returned order must match the one created, got {data[0]['id']!r}"


def test_order_adverse_action_sub_resource_returns_empty_array_when_no_adverse_action(api):
    """The sub-resource list returns at most one row; when the order is
    COMPLETE with overall_result=CLEAR, no AdverseAction was created, and
    the response is the empty array (not a 404).

    PRD §2.5: "Several endpoints expose a sub-resource form for FK
    reverse-reachability — listing the consents under an application, the
    verifications under an order, or the (at most one) adverse-action
    under an order."
    PRD §2.2: "The `response_type` is either "object" for a single
    resource or "array" for a list of resources."
    PRD §3.4: "Whenever the order's status recompute lands on `COMPLETE`
    with `overall_result` equal to `CONSIDER` — whether via the
    `IN_REVIEW` to `COMPLETE` transition or via the atomic-burst `PENDING`
    to `COMPLETE` transition — the cascade also auto-creates a single
    `AdverseAction` row in `PRE_ADVERSE_SENT`"

    Design: Corner/endpoints/fk_reverse_reachability_order_adverse_action_sub_resource_empty_array
    """
    # All-PASS → overall_result=CLEAR → no AdverseAction.
    (jur, applicant, app, consent, order,
     crim, mvr, edu) = order_complete_with_results(
         crim_result="PASS", mvr_result="PASS", edu_result="PASS",
         state_code="VT", recruiter_id="rec-001",
    )
    aa_resp = api.list_order_adverse_action(order["id"], CO)
    body = aa_resp.json() if hasattr(aa_resp, "json") else aa_resp
    assert body.get("response_type") == "array", \
        f"adverse-action sub-resource must return array envelope, got {body.get('response_type')!r}"
    data = body.get("data", [])
    assert isinstance(data, list) and len(data) == 0, \
        f"CLEAR order has no AdverseAction; sub-resource must be empty array, got {data!r}"
