"""Licensing-determination boundary claims (PRD 3.3): the exemption
eligibility threshold at seat_capacity 10 vs 11."""
from test_helpers import (
    ApiErrorId,
    api_client,
    create_licensing_determination_payload,
    validate_error,
    validate_success,
    TEST_USERS,
)
from test_helpers.fixtures import (
    create_guide,
    create_guide_assignment,
    get_pod,
    set_clock,
    setup_pod_forming,
)

ADMIN = TEST_USERS["platform_admin_headers"]
OPERATOR = TEST_USERS["pod_operator_headers"]
OFFICER = TEST_USERS["compliance_officer_headers"]


def _pod_in_review(seat_capacity: int):
    """Pod walked to LICENSING_REVIEW with an UNDER_REVIEW determination and
    a SCHEDULED guide assignment covering the term (so a grant cascades the
    pod to ACTIVE). Returns (pod_id, determination)."""
    pod, site, policy, plan = setup_pod_forming(
        pod_overrides={"seat_capacity": seat_capacity},
    )
    guide = create_guide()
    create_guide_assignment(pod["id"], guide["id"])
    det = validate_success(
        api_client.create_licensing_determination(
            pod["id"], create_licensing_determination_payload(), OPERATOR
        ),
        expected_status=201,
    )
    validate_success(
        api_client.begin_review_licensing_determination(pod["id"], det["id"], OFFICER)
    )
    return pod["id"], det


class TestExemptionCapacityThreshold:
    def test_exemption_granted_at_capacity_10(self, api):
        """PRD 3.3: "Deciding `EXEMPT_GRANTED` requires the pod's
        `seat_capacity` to be no more than 10 seats — the exemption
        eligibility threshold, beyond which full licensure is mandatory —
        and the host site's `zoning_class` to be one of
        `RESIDENTIAL_SINGLE`, `RELIGIOUS`, or `AGRICULTURAL`; a pod or site
        failing either test is rejected with `ERR_EXEMPTION_NOT_ELIGIBLE`
        (HTTP 422)."

        Design: Difficulty/boundary_precision_check/exemption_capacity_threshold_10_vs_11
        """
        set_clock("2026-06-01T00:00:00Z")
        pod_id, det = _pod_in_review(seat_capacity=10)
        decided = validate_success(
            api.decide_licensing_determination(
                pod_id, det["id"], {"decision": "EXEMPT_GRANTED"}, OFFICER
            )
        )
        assert decided["determination_status"] == "EXEMPT_GRANTED"
        pod = get_pod(pod_id)
        assert pod["status"] == "ACTIVE", (
            f"grant must cascade pod LICENSING_REVIEW -> ACTIVE, got {pod['status']}"
        )

    def test_exemption_denied_at_capacity_11(self, api):
        """PRD 3.3: "Deciding `EXEMPT_GRANTED` requires the pod's
        `seat_capacity` to be no more than 10 seats — the exemption
        eligibility threshold, beyond which full licensure is mandatory —
        and the host site's `zoning_class` to be one of
        `RESIDENTIAL_SINGLE`, `RELIGIOUS`, or `AGRICULTURAL`; a pod or site
        failing either test is rejected with `ERR_EXEMPTION_NOT_ELIGIBLE`
        (HTTP 422)."

        Design: Difficulty/boundary_precision_check/exemption_capacity_threshold_10_vs_11
        """
        set_clock("2026-06-01T00:00:00Z")
        pod_id, det = _pod_in_review(seat_capacity=11)
        resp = api.decide_licensing_determination(
            pod_id, det["id"], {"decision": "EXEMPT_GRANTED"}, OFFICER
        )
        validate_error(resp, ApiErrorId.ERR_EXEMPTION_NOT_ELIGIBLE,
                       expected_status=422)
        det_now = validate_success(
            api.get_licensing_determination(det["id"], OFFICER)
        )
        assert det_now["determination_status"] == "UNDER_REVIEW", (
            "a rejected decision must leave the determination UNDER_REVIEW, "
            f"got {det_now['determination_status']}"
        )
