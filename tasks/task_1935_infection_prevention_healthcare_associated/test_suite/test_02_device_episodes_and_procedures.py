"""Device-episode and surgical-procedure interval semantics and state gates
(PRD §3.3, §3.9)."""
from test_helpers import (
    ApiErrorId,
    create_device_episode,
    create_isolation_order,
    create_surgical_procedure,
    remove_device_episode,
    setup_unit_with_patient,
    start_isolation_order,
    discontinue_isolation_order,
    validate_error,
    validate_paginated,
    validate_success,
)


def _setup_patient_with_removed_central_line(api, nurse_manager_headers):
    """Patient whose CENTRAL_LINE episode ran 2026-08-01T10:00 -> 08-03T14:00."""
    ctx = setup_unit_with_patient()
    episode = create_device_episode(
        ctx["patient"]["id"], placed_at="2026-08-01T10:00:00Z"
    )
    remove_device_episode(episode["id"], "2026-08-03T14:00:00Z")
    ctx["episode"] = episode
    return ctx


def test_device_episode_overlap_inside_prior_interval_rejected(
    api, nurse_manager_headers
):
    """PRD §3.3: "Two episodes for the same patient and the same `device_type`
    may not overlap: their half-open intervals `[placed_at, removed_at)` must be
    disjoint, and a collision is rejected with `ERR_DEVICE_EPISODE_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/device_episode_half_open_adjacency_allowed
    """
    ctx = _setup_patient_with_removed_central_line(api, nurse_manager_headers)
    resp = api.create_device_episode(
        {
            "patient_id": ctx["patient"]["id"],
            "device_type": "CENTRAL_LINE",
            "placed_at": "2026-08-03T12:00:00Z",
        },
        nurse_manager_headers,
    )
    validate_error(resp, ApiErrorId.ERR_DEVICE_EPISODE_OVERLAP)
    episodes, meta = validate_paginated(
        api.list_device_episodes(
            nurse_manager_headers,
            params={"patient_id": ctx["patient"]["id"], "device_type": "CENTRAL_LINE"},
        )
    )
    assert meta["total_count"] == 1, "the rejected overlapping episode must not persist"


def test_device_episode_back_to_back_placement_permitted(api, nurse_manager_headers):
    """PRD §3.3: "Because the interval is half-open, a back-to-back placement —
    one episode's `placed_at` exactly equal to another's `removed_at` — is
    permitted."

    Design: Difficulty/resource_temporal_overlap/device_episode_half_open_adjacency_allowed
    """
    ctx = _setup_patient_with_removed_central_line(api, nurse_manager_headers)
    resp = api.create_device_episode(
        {
            "patient_id": ctx["patient"]["id"],
            "device_type": "CENTRAL_LINE",
            "placed_at": "2026-08-03T14:00:00Z",
        },
        nurse_manager_headers,
    )
    episode = validate_success(resp, 201)
    assert episode["status"] == "ACTIVE"
    episodes, meta = validate_paginated(
        api.list_device_episodes(
            nurse_manager_headers,
            params={"patient_id": ctx["patient"]["id"], "device_type": "CENTRAL_LINE"},
        )
    )
    assert meta["total_count"] == 2, (
        f"back-to-back placement must be stored; total_count was {meta['total_count']}"
    )


def _setup_patient_with_procedure(api, nurse_manager_headers):
    """OR unit patient with procedure P1 occupying [08-02T09:00, 08-02T10:00]."""
    ctx = setup_unit_with_patient(unit_type="OR")
    proc = create_surgical_procedure(
        ctx["patient"]["id"],
        procedure_code="COLO",
        performed_at="2026-08-02T09:00:00Z",
        duration_minutes=60,
        asa_score=2,
        wound_class="CLEAN",
    )
    ctx["procedure"] = proc
    return ctx


def test_procedure_touching_at_closed_end_conflicts(api, nurse_manager_headers):
    """PRD §3.3: "A procedure occupies the closed interval from `performed_at`
    through `performed_at` plus `duration_minutes`, inclusive of both endpoints;
    two procedures for the same patient whose closed intervals share even a
    single instant are rejected with `ERR_PROCEDURE_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/surgical_procedure_closed_interval_touching_conflicts
    """
    ctx = _setup_patient_with_procedure(api, nurse_manager_headers)
    resp = api.create_surgical_procedure(
        {
            "patient_id": ctx["patient"]["id"],
            "procedure_code": "APPY",
            "performed_at": "2026-08-02T10:00:00Z",
            "duration_minutes": 30,
            "asa_score": 1,
            "wound_class": "CLEAN",
        },
        nurse_manager_headers,
    )
    validate_error(resp, ApiErrorId.ERR_PROCEDURE_OVERLAP)
    _, meta = validate_paginated(
        api.list_surgical_procedures(
            nurse_manager_headers, params={"patient_id": ctx["patient"]["id"]}
        )
    )
    assert meta["total_count"] == 1, "the touching procedure must not persist"


def test_procedure_one_second_after_closed_end_permitted(api, nurse_manager_headers):
    """PRD §3.3: "A procedure occupies the closed interval from `performed_at`
    through `performed_at` plus `duration_minutes`, inclusive of both endpoints;
    two procedures for the same patient whose closed intervals share even a
    single instant are rejected with `ERR_PROCEDURE_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/surgical_procedure_closed_interval_touching_conflicts
    """
    ctx = _setup_patient_with_procedure(api, nurse_manager_headers)
    resp = api.create_surgical_procedure(
        {
            "patient_id": ctx["patient"]["id"],
            "procedure_code": "APPY",
            "performed_at": "2026-08-02T10:00:01Z",
            "duration_minutes": 30,
            "asa_score": 1,
            "wound_class": "CLEAN",
        },
        nurse_manager_headers,
    )
    proc = validate_success(resp, 201)
    assert proc["performed_at"]
    _, meta = validate_paginated(
        api.list_surgical_procedures(
            nurse_manager_headers, params={"patient_id": ctx["patient"]["id"]}
        )
    )
    assert meta["total_count"] == 2, (
        f"procedure one second past the closed end must be stored; got {meta['total_count']}"
    )


def test_terminal_state_lockdowns_on_episodes_and_orders(
    api, nurse_manager_headers, ip_headers
):
    """PRD §3.3: "Removal, performed by a `UnitNurseManager` supplying
    `removed_at`, requires the episode to be `ACTIVE`
    (`ERR_DEVICE_EPISODE_NOT_ACTIVE` otherwise) and requires `removed_at` to be
    no earlier than `placed_at` (`ERR_INVALID_REQUEST`); it transitions the
    episode to `REMOVED`."
    PRD §3.9: "Compliance audits are performed by a `UnitNurseManager` against
    an `ACTIVE` order — auditing an order in any other status is rejected with
    `ERR_ISOLATION_ORDER_NOT_ACTIVE`."
    PRD §3.9: "A `UnitNurseManager` starts an order that is `ORDERED`
    (`ERR_ISOLATION_ORDER_NOT_STARTABLE` otherwise), which sets `started_at` and
    lands the status axis in `ACTIVE`."
    PRD §3.9: "Discontinuing works from either `ORDERED` or `ACTIVE`
    (`ERR_ISOLATION_ALREADY_DISCONTINUED` otherwise), sets `discontinued_at`,
    and lands the order in terminal `DISCONTINUED` — while leaving
    `compliance_status` exactly as it stands."

    Design: Corner/validations/device_episode_double_remove_and_audit_on_inactive_order
    """
    ctx = setup_unit_with_patient(unit_type="WARD")
    patient_id = ctx["patient"]["id"]
    episode = create_device_episode(
        patient_id, device_type="URINARY_CATHETER", placed_at="2026-08-01T10:00:00Z"
    )
    remove_device_episode(episode["id"], "2026-08-05T10:00:00Z")

    order_ordered = create_isolation_order(patient_id, precaution_type="DROPLET")
    order_discontinued = create_isolation_order(patient_id, precaution_type="CONTACT")
    start_isolation_order(order_discontinued["id"])
    discontinue_isolation_order(order_discontinued["id"])

    resp1 = api.remove_device_episode(
        episode["id"], {"removed_at": "2026-08-06T10:00:00Z"}, nurse_manager_headers
    )
    validate_error(resp1, ApiErrorId.ERR_DEVICE_EPISODE_NOT_ACTIVE)

    audit_payload = {
        "observed_at": "2026-08-02T09:00:00Z",
        "elements_checked": 10,
        "elements_passed": 10,
    }
    resp2 = api.create_isolation_audit(
        {"isolation_order_id": order_ordered["id"], **audit_payload},
        nurse_manager_headers,
    )
    validate_error(resp2, ApiErrorId.ERR_ISOLATION_ORDER_NOT_ACTIVE)

    resp3 = api.create_isolation_audit(
        {"isolation_order_id": order_discontinued["id"], **audit_payload},
        nurse_manager_headers,
    )
    validate_error(resp3, ApiErrorId.ERR_ISOLATION_ORDER_NOT_ACTIVE)

    resp4 = api.start_isolation_order(order_discontinued["id"], nurse_manager_headers)
    validate_error(resp4, ApiErrorId.ERR_ISOLATION_ORDER_NOT_STARTABLE)

    resp5 = api.discontinue_isolation_order(
        order_discontinued["id"], nurse_manager_headers
    )
    validate_error(resp5, ApiErrorId.ERR_ISOLATION_ALREADY_DISCONTINUED)
