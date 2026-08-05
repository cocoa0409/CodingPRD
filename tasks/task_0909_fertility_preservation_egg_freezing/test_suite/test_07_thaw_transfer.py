"""Thaw/transfer authorization: the authorize/deny fork, the execute cascade, directive and
segregation-of-duties safety gates, specimen-state guards, and tank-slot conservation.
"""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, TEST_USERS,
    create_directive_payload, create_thaw_authorization_payload,
)
from test_helpers import fixtures as fx

COORD = TEST_USERS["coordinator_headers"]


# --------------------------------------------------------------- Difficulty: authorize/deny fork
def test_authorize_reserves_specimens(api):
    """PRD §3.7: "On success the server pins the active consent directive as consent_directive_id
    and the active disposition directive as disposition_directive_id, records the acting physician
    as authorizer_provider_id, and cascades each referenced CryoSpecimen from STORED to RESERVED."

    Design: Difficulty/non_linear_state_machine/thaw_authorization_branching_forkjoin
    """
    b = fx.setup_thaw_ready(mature_oocyte_count=2)
    s0 = b["specimen_ids"][0]
    auth_id = fx.request_thaw(b["patient_id"], [s0], b["phys_id"])
    auth = fx.authorize_thaw(auth_id, b["phys2_id"])
    assert auth["status"] == "AUTHORIZED", "authorize must move REQUESTED -> AUTHORIZED"
    spec = validate_success(api.get_cryo_specimen(s0, COORD), 200)
    assert spec["status"] == "RESERVED", "authorized specimen must move STORED -> RESERVED"


def test_deny_leaves_specimens_stored(api):
    """PRD §3.7: "the authorizing Physician may deny a requested authorization, moving it from
    REQUESTED to DENIED; denial is a divergent branch that reserves nothing and produces no
    specimen state change."

    Design: Difficulty/non_linear_state_machine/thaw_authorization_branching_forkjoin
    """
    b = fx.setup_thaw_ready(mature_oocyte_count=2)
    s0 = b["specimen_ids"][0]
    auth_id = fx.request_thaw(b["patient_id"], [s0], b["phys_id"], transfer_type="RESEARCH_DONATION")
    data = validate_success(api.deny_thaw(auth_id, fx.make_physician_headers(b["phys2_id"])), 200)
    assert data["status"] == "DENIED", "deny must move REQUESTED -> DENIED"
    spec = validate_success(api.get_cryo_specimen(s0, COORD), 200)
    assert spec["status"] == "STORED", "denied specimen must remain STORED"


# --------------------------------------------------------------- Difficulty: execute cascade depth-3
def test_execute_thaws_specimens_and_frees_tank_slots(api):
    """PRD §3.7: "execution cascades each referenced specimen from `RESERVED` to `THAWED`,
    decrementing its tank's `used_slots`, decrementing the patient's
    `StorageSubscription.specimen_count`, and recomputing that subscription's storage renewal fee."

    Design: Difficulty/transitive_cascade/thaw_execute_cascade_depth3
    """
    b = fx.setup_thaw_ready(mature_oocyte_count=2, tank_capacity=10)
    s0, s1 = b["specimen_ids"][0], b["specimen_ids"][1]
    auth_id = fx.request_thaw(b["patient_id"], [s0, s1], b["phys_id"])
    fx.authorize_thaw(auth_id, b["phys2_id"])
    data = validate_success(api.execute_thaw(auth_id, fx.make_embryologist_headers(b["emb_id"])), 200)
    assert data["status"] == "EXECUTED", "execute must move AUTHORIZED -> EXECUTED"
    spec = validate_success(api.get_cryo_specimen(s0, COORD), 200)
    assert spec["status"] == "THAWED", "executed specimen must be THAWED"
    tank = validate_success(api.get_storage_tank(b["tank_id"], COORD), 200)
    assert tank["used_slots"] == 0, f"both slots must free on thaw, got {tank['used_slots']}"


def test_execute_decrements_subscription_and_recomputes_fee(api):
    """PRD §3.7: "decrementing the patient's StorageSubscription.specimen_count, and recomputing
    that subscription's storage renewal fee." PRD §2.7: "its annual_fee_cents is the most recent
    storage-renewal-fee result over that count."

    Design: Difficulty/transitive_cascade/thaw_execute_cascade_depth3
    """
    b = fx.setup_thaw_ready(mature_oocyte_count=2, tank_capacity=10)
    s0, s1 = b["specimen_ids"][0], b["specimen_ids"][1]
    auth_id = fx.request_thaw(b["patient_id"], [s0, s1], b["phys_id"])
    fx.authorize_thaw(auth_id, b["phys2_id"])
    validate_success(api.execute_thaw(auth_id, fx.make_embryologist_headers(b["emb_id"])), 200)
    sub = validate_success(api.get_storage_subscription(b["subscription_id"], COORD), 200)
    assert sub["specimen_count"] == 0, f"count must fall to 0, got {sub['specimen_count']}"
    assert sub["annual_fee_cents"] == 0, f"fee over 0 specimens must be 0, got {sub['annual_fee_cents']}"


# --------------------------------------------------------------- Difficulty: directive safety gates
def test_authorize_without_disposition_directive_rejected(api):
    """PRD §3.7: "The patient must likewise have an ACTIVE DISPOSITION directive, absent which
    the request is rejected with ERR_DISPOSITION_NOT_ACTIVE."

    Design: Difficulty/cross_entity_state_dependency/thaw_authorize_requires_active_directives
    """
    b = fx.setup_retrieved_cycle(mature_oocyte_count=1, tank_capacity=10, with_subscription=True)
    fx.create_consent_only(b["patient_id"])  # consent only, no disposition
    phys2 = fx.create_physician("Dr AuthDisp")
    auth_id = fx.request_thaw(b["patient_id"], [b["specimen_ids"][0]], b["phys_id"])
    resp = api.authorize_thaw(auth_id, fx.make_physician_headers(phys2))
    validate_error(resp, ApiErrorId.ERR_DISPOSITION_NOT_ACTIVE.value, 422)


def test_authorize_without_consent_directive_rejected(api):
    """PRD §3.7: "The patient must have an active consent on file: absent an ACTIVE CONSENT
    directive, the request is rejected with ERR_CONSENT_NOT_ACTIVE."

    Design: Difficulty/cross_entity_state_dependency/thaw_authorize_requires_active_directives
    """
    b = fx.setup_retrieved_cycle(mature_oocyte_count=1, tank_capacity=10, with_subscription=True)
    phys2 = fx.create_physician("Dr AuthCons")
    auth_id = fx.request_thaw(b["patient_id"], [b["specimen_ids"][0]], b["phys_id"])
    resp = api.authorize_thaw(auth_id, fx.make_physician_headers(phys2))
    validate_error(resp, ApiErrorId.ERR_CONSENT_NOT_ACTIVE.value, 422)


# --------------------------------------------------------------- Difficulty: safety beats referential
def test_revoked_consent_reported_before_foreign_specimen(api):
    """PRD §2.9: "A lower priority number always wins." PRD §3.7 narrates the checks in order:
    "The patient must have an active consent on file: absent an ACTIVE CONSENT directive, the
    request is rejected with ERR_CONSENT_NOT_ACTIVE." (before) "Every specimen named in
    specimen_ids must belong to the authorization's patient — otherwise ERR_SPECIMEN_NOT_OWNED."

    Design: Difficulty/priority_pair_validation_conflict/thaw_safety_beats_referential
    """
    # Q owns a real STORED specimen.
    q = fx.setup_retrieved_cycle(mature_oocyte_count=1, tank_capacity=10)
    q_spec = q["specimen_ids"][0]
    # P has a CONSENT that is then revoked, plus an ACTIVE DISPOSITION.
    p = fx.create_patient()
    p_headers = fx.make_patient_headers(p["id"])
    v1 = fx.get_patient_version(p["id"])
    consent_id = fx.get_success_data(api.create_directive(
        create_directive_payload(p["id"], v1, directive_type="CONSENT"), p_headers))["id"]
    v2 = fx.get_patient_version(p["id"])
    fx.get_success_data(api.create_directive(
        create_directive_payload(p["id"], v2, directive_type="DISPOSITION",
                                 disposition_action="THAW_TO_SELF"), p_headers))
    validate_success(api.revoke_directive(consent_id, p_headers), 200)
    # Auth for P references Q's foreign specimen; requester != authorizer.
    phys_b = fx.create_physician("Dr SafeAuth")
    auth_id = fx.request_thaw(p["id"], [q_spec], q["phys_id"])
    resp = api.authorize_thaw(auth_id, fx.make_physician_headers(phys_b))
    validate_error(resp, ApiErrorId.ERR_CONSENT_NOT_ACTIVE.value, 422)


def test_missing_consent_reported_before_foreign_specimen(api):
    """PRD §2.9: "A lower priority number always wins." PRD §3.7: "The patient must have an
    active consent on file: absent an ACTIVE CONSENT directive, the request is rejected with
    ERR_CONSENT_NOT_ACTIVE." (before) "Every specimen named in specimen_ids must belong to the
    authorization's patient — otherwise ERR_SPECIMEN_NOT_OWNED."

    Design: Difficulty/priority_pair_validation_conflict/thaw_safety_beats_referential
    """
    q = fx.setup_retrieved_cycle(mature_oocyte_count=1, tank_capacity=10)
    q_spec = q["specimen_ids"][0]
    # P has only a DISPOSITION directive; no CONSENT ever created.
    p = fx.create_patient()
    p_headers = fx.make_patient_headers(p["id"])
    v1 = fx.get_patient_version(p["id"])
    fx.get_success_data(api.create_directive(
        create_directive_payload(p["id"], v1, directive_type="DISPOSITION",
                                 disposition_action="THAW_TO_SELF"), p_headers))
    phys_b = fx.create_physician("Dr SafeAuth2")
    auth_id = fx.request_thaw(p["id"], [q_spec], q["phys_id"])
    resp = api.authorize_thaw(auth_id, fx.make_physician_headers(phys_b))
    validate_error(resp, ApiErrorId.ERR_CONSENT_NOT_ACTIVE.value, 422)


# --------------------------------------------------------------- Difficulty: tank slot conservation
def test_tank_slots_conserved_after_partial_thaw(api):
    """PRD §2.7: "A specimen moving into `RESERVED` does not change `used_slots` (it still
    occupies its slot); a specimen moving to `THAWED` or `DISCARDED` frees its slot and
    decrements `used_slots`."

    Design: Difficulty/compensating_invariant/tank_slot_conservation_store_thaw
    """
    b = fx.setup_thaw_ready(mature_oocyte_count=2, tank_capacity=5)
    s0 = b["specimen_ids"][0]
    auth_id = fx.request_thaw(b["patient_id"], [s0], b["phys_id"])
    fx.authorize_thaw(auth_id, b["phys2_id"])
    validate_success(api.execute_thaw(auth_id, fx.make_embryologist_headers(b["emb_id"])), 200)
    tank = validate_success(api.get_storage_tank(b["tank_id"], COORD), 200)
    assert tank["used_slots"] == 1, f"one remaining stored specimen => used_slots 1, got {tank['used_slots']}"


def test_partial_thaw_leaves_other_specimen_stored(api):
    """PRD §2.7: "A specimen moving into `RESERVED` does not change `used_slots` (it still
    occupies its slot); a specimen moving to `THAWED` or `DISCARDED` frees its slot and
    decrements `used_slots`."

    Design: Difficulty/compensating_invariant/tank_slot_conservation_store_thaw
    """
    b = fx.setup_thaw_ready(mature_oocyte_count=2, tank_capacity=5)
    s0, s1 = b["specimen_ids"][0], b["specimen_ids"][1]
    auth_id = fx.request_thaw(b["patient_id"], [s0], b["phys_id"])
    fx.authorize_thaw(auth_id, b["phys2_id"])
    validate_success(api.execute_thaw(auth_id, fx.make_embryologist_headers(b["emb_id"])), 200)
    assert validate_success(api.get_cryo_specimen(s0, COORD), 200)["status"] == "THAWED"
    assert validate_success(api.get_cryo_specimen(s1, COORD), 200)["status"] == "STORED"


# --------------------------------------------------------------- Corner: guards
def test_execute_before_authorize_invalid_state(api):
    """PRD §2.7: "Any attempt to drive a resource through a transition for which it is not in
    the correct originating state is rejected with ERR_INVALID_STATE." PRD §3.7: "Execution ...
    moving the authorization from AUTHORIZED to EXECUTED."

    Design: Corner/state_machines/execute_before_authorize_returns_invalid_state
    """
    b = fx.setup_thaw_ready(mature_oocyte_count=1, tank_capacity=10)
    # Build a genuine REQUESTED authorization (not yet AUTHORIZED).
    auth_id = fx.request_thaw(b["patient_id"], [b["specimen_ids"][0]], b["phys_id"])
    resp = api.execute_thaw(auth_id, fx.make_embryologist_headers(b["emb_id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)


def test_authorize_same_provider_as_requester_segregation(api):
    """PRD §3.7: "The acting physician's X-User-ID must differ from the requester_provider_id;
    if the same physician who requested attempts to authorize, the request is rejected with
    ERR_SEGREGATION_OF_DUTIES."

    Design: Corner/errors/thaw_authorize_same_provider_returns_segregation
    """
    b = fx.setup_retrieved_cycle(mature_oocyte_count=1, tank_capacity=10, with_subscription=True)
    fx.create_directives(b["patient_id"])
    auth_id = fx.request_thaw(b["patient_id"], [b["specimen_ids"][0]], b["phys_id"])
    resp = api.authorize_thaw(auth_id, fx.make_physician_headers(b["phys_id"]))
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, 409)


def test_authorize_already_reserved_specimen_not_available(api):
    """PRD §3.7: "each must currently be in STORED status; a specimen not in the required state
    is rejected with ERR_SPECIMEN_NOT_AVAILABLE."

    Design: Corner/errors/authorize_reserved_specimen_returns_specimen_not_available
    """
    b = fx.setup_thaw_ready(mature_oocyte_count=1, tank_capacity=10)
    s0 = b["specimen_ids"][0]
    auth1 = fx.request_thaw(b["patient_id"], [s0], b["phys_id"])
    fx.authorize_thaw(auth1, b["phys2_id"])  # s0 now RESERVED
    auth2 = fx.request_thaw(b["patient_id"], [s0], b["phys_id"], transfer_type="TRANSFER_OUT")
    resp = api.authorize_thaw(auth2, fx.make_physician_headers(b["phys2_id"]))
    validate_error(resp, ApiErrorId.ERR_SPECIMEN_NOT_AVAILABLE.value, 409)
