"""Authentication and role-based access control (PRD §2.1, §2.7, §4)."""
from test_helpers import (
    api_client, TEST_USERS, ApiErrorId, validate_error, validate_success,
    create_horse_payload, barn_shift_payload, adopter_payload,
    make_adopter_headers, make_sponsor_headers, make_farrier_headers,
    make_volunteer_headers,
    register_adopter, register_sponsor, register_volunteer, register_vet,
    register_farrier, intake_horse, complete_medical_pass, clear_active_protocol,
    release_horse, propose_case, get_case, create_sponsorship, get_sponsorship,
)

INTAKE = TEST_USERS["intake_headers"]


class TestAuthentication:
    def test_missing_auth_returns_unauthenticated(self):
        """PRD §2.1: "A request missing either header, or presenting a role the
        system does not declare, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/validations/missing_auth_returns_unauthenticated
        """
        resp = api_client.list_horses(headers={})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED, 401)


class TestRoleExclusivity:
    def test_adopter_cannot_intake_horse(self):
        """PRD §2.1: "After authentication, the caller's role must appear in the
        target endpoint's authorized-role list; otherwise the request fails with
        `ERR_FORBIDDEN` (HTTP 403)." (POST /rescue-ops/horses lists only
        IntakeCoordinator, PRD §4.)

        Design: Corner/rbac/adopter_cannot_intake_horse
        """
        adopter = register_adopter()
        resp = api_client.create_horse(
            create_horse_payload(name="Sneak"),
            make_adopter_headers(adopter["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN, 403)

    def test_volunteer_cannot_create_shift(self):
        """PRD §2.1: "After authentication, the caller's role must appear in the
        target endpoint's authorized-role list; otherwise the request fails with
        `ERR_FORBIDDEN` (HTTP 403)." (POST /rescue-ops/barn-shifts lists only
        VolunteerCoordinator, PRD §4.)

        Design: Corner/rbac/volunteer_cannot_create_shift
        """
        volunteer = register_volunteer()
        resp = api_client.create_barn_shift(
            barn_shift_payload(), make_volunteer_headers(volunteer["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN, 403)

    def test_farrier_cannot_certify_case(self):
        """PRD §2.1: "After authentication, the caller's role must appear in the
        target endpoint's authorized-role list; otherwise the request fails with
        `ERR_FORBIDDEN` (HTTP 403)." (POST
        /rescue-ops/euthanasia-cases/{id}/certify lists only Veterinarian, PRD §4.)

        Design: Corner/rbac/farrier_cannot_certify_case
        """
        vet_id = register_vet()
        farrier_id = register_farrier()
        bundle = intake_horse(age_years=17, body_condition_score=4)
        complete_medical_pass(bundle["id"])
        clear_active_protocol(bundle["id"], vet_id)
        release_horse(bundle["id"], "REHABILITATION")
        case = propose_case(bundle["id"], vet_id, suffering_score=6,
                            clinical_summary="chronic pain")

        resp = api_client.certify_euthanasia_case(
            case["id"], {"decision": "CONCUR", "emergency_attestation": False},
            make_farrier_headers(farrier_id))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN, 403)
        assert get_case(case["id"])["status"] == "PROPOSED"

    def test_sponsor_cannot_activate_others_sponsorship(self):
        """PRD §2.1: "a `Sponsor` may create, activate, reinstate, or cancel only
        sponsorships whose `sponsor_id` equals their own id, and may read only
        their own sponsor record"
        PRD §3.6: "a sponsor-role caller must own the sponsorship
        (`ERR_FORBIDDEN`)"

        Design: Corner/rbac/sponsor_cannot_activate_others_sponsorship
        """
        horse = intake_horse()
        sp1 = register_sponsor(name="SP1", contact_email="s1@x.com")
        sp2 = register_sponsor(name="SP2", contact_email="s2@x.com")
        sponsorship = create_sponsorship(sp2["id"], horse["id"], 3000)
        assert sponsorship["status"] == "PLEDGED"

        resp = api_client.activate_sponsorship(
            sponsorship["id"], make_sponsor_headers(sp1["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN, 403)

        ok = validate_success(api_client.activate_sponsorship(
            sponsorship["id"], make_sponsor_headers(sp2["id"])))
        assert ok["status"] == "ACTIVE"

    def test_adopter_self_scope_read(self):
        """PRD §2.1: "an `Adopter` may submit applications only under their own
        `adopter_id`, withdraw and pay fees only on their own applications, and
        read only their own adopter record"

        Design: Corner/rbac/adopter_self_scope_read
        """
        ad1 = register_adopter(full_name="Ad One", contact_email="a1@x.com")
        ad2 = register_adopter(full_name="Ad Two", contact_email="a2@x.com",
                               experience_level="NOVICE", has_stall_facility=False)

        own = validate_success(
            api_client.get_adopter(ad1["id"], make_adopter_headers(ad1["id"])))
        assert own["id"] == ad1["id"]

        resp = api_client.get_adopter(ad2["id"], make_adopter_headers(ad1["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN, 403)
