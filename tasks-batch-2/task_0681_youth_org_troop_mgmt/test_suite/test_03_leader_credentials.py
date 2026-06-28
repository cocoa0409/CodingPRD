"""Leader credentials: background-check lifecycle, training, segregation of duties."""
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
    make_registrar_headers,
    create_council_and_troop,
    create_member,
    create_leader_credential_payload,
)

REG = TEST_USERS["registrar_headers"]
LEAD = TEST_USERS["leader_headers"]


def _adult_with_credential(api, requested_by="leader-bob", unit_number="S-3", name="C"):
    council, troop = create_council_and_troop(
        council_overrides={"name": name}, troop_overrides={"unit_number": unit_number}
    )
    member = create_member(troop["id"], member_type="ADULT", full_name="Adult L", birthdate="1980-01-01")
    cred = get_success_data(
        api.create_leader_credential(
            member["id"], create_leader_credential_payload(requested_by_user_id=requested_by), LEAD
        )
    )
    return council, troop, member, cred


def test_resolve_bgcheck_before_start_is_invalid_state(api):
    """PRD §3.4: "The background-check dimension is the lifecycle axis: a registrar
    starts the check, moving bgcheck_status from NOT_STARTED to PENDING. From
    PENDING the registrar resolves it by supplying an outcome."
    PRD §3.4: "Any background-check or training transition attempted from a state
    where it is not defined is rejected with ERR_INVALID_STATE."

    Design: Corner/state_machines/bgcheck_resolve_before_start_invalid_state
    """
    _c, _t, _m, cred = _adult_with_credential(api, unit_number="S-3", name="S3")
    resp = api.resolve_bgcheck(cred["id"], {"outcome": "CLEAR"}, make_registrar_headers("registrar-amy"))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_leader_credential_on_youth_rejected(api):
    """PRD §3.4: "The credential may only be opened against a member whose
    member_type is ADULT; attempting it on a youth is rejected with
    ERR_MEMBER_NOT_REGISTERED."

    Design: Corner/validations/leader_credential_on_youth_rejected
    """
    council, troop = create_council_and_troop(
        council_overrides={"name": "V5"}, troop_overrides={"unit_number": "V-5"}
    )
    youth = create_member(troop["id"], member_type="YOUTH", full_name="Youth Not Leader")
    resp = api.create_leader_credential(
        youth["id"], create_leader_credential_payload(requested_by_user_id="leader-bob"), LEAD
    )
    validate_error(resp, ApiErrorId.ERR_MEMBER_NOT_REGISTERED.value)


def test_resolve_own_bgcheck_rejected_segregation(api):
    """PRD §3.4: "Both resolutions are subject to segregation of duties: the
    resolving operator's X-User-ID must differ from the credential's
    requested_by_user_id, and a self-resolution is rejected with
    ERR_SEGREGATION_OF_DUTIES."

    Design: Corner/rbac/segregation_resolve_own_bgcheck_direct
    """
    _c, _t, _m, cred = _adult_with_credential(api, requested_by="registrar-amy", unit_number="R-4", name="R4")
    get_success_data(api.start_bgcheck(cred["id"], REG))
    # Resolver X-User-ID equals the recorded requester id -> self-resolution.
    resp = api.resolve_bgcheck(cred["id"], {"outcome": "CLEAR"}, make_registrar_headers("registrar-amy"))
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)
