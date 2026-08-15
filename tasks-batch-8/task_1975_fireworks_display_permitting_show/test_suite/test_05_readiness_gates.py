"""Security posts, readiness aggregate gates, crew certification (PRD §3.5, §2.5)."""
import pytest

from test_helpers import (
    ApiErrorId,
    create_assign_payload,
    create_crew_member_payload,
    create_security_post_payload,
    get_success_data,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import (
    add_lead_crew,
    add_secured_post,
    checkout_product,
    create_magazine_with_batch,
    create_operator,
    setup_event_standby_confirmed,
)


class TestSecurityPostStaffing:
    def test_post_secured_at_exact_required_then_assign_rejected(self, api):
        """PRD §3.5: "the moment `assigned_guards` reaches `required_guards` —
        inclusive equality secures — the post auto-transitions to `SECURED`"
        and assignments are "allowed while the post is `UNSTAFFED` or
        `STAFFED`"; PRD §2.8: an unlisted transition yields
        `ERR_INVALID_STATE`. Guard math per §3.5: "take the arc length in feet
        — two times pi times `radius_ft`, scaled by the fraction `arc_degrees`
        over 360 ... divide by the 100-foot guard-spacing constant, round up,
        and floor the result at a minimum of one guard".

        Design: Corner/state_machines/post_secured_at_exact_required_then_assign_rejected
        """
        op, op_headers, ev, sp, app = setup_event_standby_confirmed()
        post = get_success_data(api.create_security_post(
            ev["id"], create_security_post_payload(arc_degrees=45, radius_ft=300), op_headers
        ))
        # ceil(2*pi*300*(45/360) / 100) = ceil(2.356..) = 3
        assert post["required_guards"] == 3
        s1 = get_success_data(api.assign_guard(post["id"], create_assign_payload("g1"), op_headers))
        assert s1["status"] == "STAFFED"
        s2 = get_success_data(api.assign_guard(post["id"], create_assign_payload("g2"), op_headers))
        assert s2["status"] == "STAFFED"
        s3 = get_success_data(api.assign_guard(post["id"], create_assign_payload("g3"), op_headers))
        assert s3["status"] == "SECURED", "inclusive equality at required_guards must secure"
        bad = api.assign_guard(post["id"], create_assign_payload("g4"), op_headers)
        validate_error(bad, ApiErrorId.ERR_INVALID_STATE)


class TestReadyGateSecurity:
    def _setup_two_of_three_guards(self, api):
        op, op_headers, ev, sp, app = setup_event_standby_confirmed()
        mag, batch = create_magazine_with_batch(op_headers)
        checkout_product(batch, ev, op_headers, 10)
        crew, crew_headers = add_lead_crew(op, op_headers)
        post = get_success_data(api.create_security_post(
            ev["id"], create_security_post_payload(arc_degrees=45, radius_ft=300), op_headers
        ))
        get_success_data(api.assign_guard(post["id"], create_assign_payload("g1"), op_headers))
        get_success_data(api.assign_guard(post["id"], create_assign_payload("g2"), op_headers))
        return op, op_headers, ev, post

    def test_ready_rejected_while_post_staffed(self, api):
        """PRD §3.5: "at least one security post exists and every post of the
        event is `SECURED`, otherwise `ERR_SECURITY_NOT_SECURED`".

        Design: Difficulty/cross_entity_state_dependency/ready_requires_security_posts_secured
        """
        op, op_headers, ev, post = self._setup_two_of_three_guards(api)
        resp = api.ready_display(ev["id"], op_headers)
        validate_error(resp, ApiErrorId.ERR_SECURITY_NOT_SECURED)
        assert resp.status_code == 409

    def test_ready_succeeds_after_post_secured(self, api):
        """PRD §3.5: "the moment `assigned_guards` reaches `required_guards` —
        inclusive equality secures — the post auto-transitions to `SECURED`"
        and readiness then moves "the event `STANDBY_CONFIRMED → READY`".

        Design: Difficulty/cross_entity_state_dependency/ready_requires_security_posts_secured
        """
        op, op_headers, ev, post = self._setup_two_of_three_guards(api)
        s3 = get_success_data(api.assign_guard(post["id"], create_assign_payload("g3"), op_headers))
        assert s3["status"] == "SECURED"
        resp = api.ready_display(ev["id"], op_headers)
        data = validate_success(resp)
        assert data["status"] == "READY"


class TestReadyGateProductAndCrew:
    def test_ready_without_product_on_site_rejected(self, api):
        """PRD §3.5: "net checked-out product for the event — total
        `CHECK_OUT` minus total `RETURN` — is greater than zero, otherwise
        `ERR_NO_PRODUCT_ON_SITE`."

        Design: Corner/validations/ready_without_product_on_site_rejected
        """
        op, op_headers, ev, sp, app = setup_event_standby_confirmed()
        add_lead_crew(op, op_headers)
        add_secured_post(ev, op_headers)
        resp = api.ready_display(ev["id"], op_headers)
        validate_error(resp, ApiErrorId.ERR_NO_PRODUCT_ON_SITE)
        fresh = get_success_data(api.get_display(ev["id"], op_headers))
        assert fresh["status"] == "STANDBY_CONFIRMED"

    def test_ready_without_lead_crew_rejected(self, api):
        """PRD §3.5: "at least one of the operator's crew holds `LEAD_OPERATOR` certification valid through `scheduled_start_at`, otherwise `ERR_CERT_NOT_VALID`".

        Design: Corner/validations/ready_without_lead_crew_rejected
        """
        op, op_headers, ev, sp, app = setup_event_standby_confirmed()
        mag, batch = create_magazine_with_batch(op_headers)
        checkout_product(batch, ev, op_headers, 10)
        # Only a SHOOTER — no LEAD_OPERATOR.
        get_success_data(api.create_crew_member(
            op["id"],
            create_crew_member_payload(full_name="Sal", cert_level="SHOOTER"),
            op_headers,
        ))
        add_secured_post(ev, op_headers)
        resp = api.ready_display(ev["id"], op_headers)
        validate_error(resp, ApiErrorId.ERR_CERT_NOT_VALID)

    def test_cert_expired_at_creation_rejected(self, api):
        """PRD §2.5: "Certification must not already be expired at
        registration — a `cert_expires_at` at or before the current clock is
        rejected with `ERR_CERT_NOT_VALID`" (startup clock is
        2026-08-01T00:00:00Z, §2.4).

        Design: Corner/validations/cert_expired_at_creation_rejected
        """
        op, op_headers = create_operator()
        resp = api.create_crew_member(
            op["id"],
            create_crew_member_payload(full_name="Ex", cert_level="SHOOTER",
                                       cert_expires_at="2026-07-01T00:00:00Z"),
            op_headers,
        )
        validate_error(resp, ApiErrorId.ERR_CERT_NOT_VALID)
        assert resp.status_code == 409
