"""Wait-estimate calculation tests: the forward-looking ahead-set sum divided by
effective servers and rounded up, plus the optimistic (RESERVED) variant that
divides by one extra fast-track server (PRD §3.2).
"""
from test_helpers import (
    api_client,
    validate_success,
    TEST_USERS,
    create_clinic,
    create_provider,
    create_walk_in,
    create_online_reservation,
    triage,
)

_MGR = TEST_USERS["clinic_manager_headers"]
_PROVIDER = TEST_USERS["provider_headers"]
_PATIENT = TEST_USERS["patient_headers"]


# ─── dual_variant_calc / wait_estimate_optimistic_vs_conservative_diverges ───

def test_wait_estimate_conservative_persisted_on_triaged_entry():
    """PRD §3.2: "The conservative variant is the one persisted on an entry once
    it has been triaged and is the figure shown on the posted board: it divides
    the work-ahead total by the effective-server count alone, as just described."

    Design: Difficulty/dual_variant_calc/wait_estimate_optimistic_vs_conservative_diverges
    """
    clinic = create_clinic(name="WaitClinic", exam_room_capacity=4)
    create_provider(clinic["id"], full_name="Solo", credential="NP", on_shift=True)
    q3 = create_walk_in(clinic["id"], chief_complaint="ahead-esi3")
    triage(clinic["id"], q3["id"], esi_level=3)
    q4 = create_walk_in(clinic["id"], chief_complaint="ahead-esi4")
    triage(clinic["id"], q4["id"], esi_level=4)
    qt = create_walk_in(clinic["id"], chief_complaint="under-test-esi5")
    triage(clinic["id"], qt["id"], esi_level=5)
    create_online_reservation(clinic["id"], chief_complaint="online-hold-esi5")

    fetched = validate_success(api_client.get_queue_entry(qt["id"], _PROVIDER), 200)
    # Ahead-set = ESI3 (20) + ESI4 (12) = 32; one on-shift server: ceil(32/1) = 32.
    assert fetched["estimated_wait_minutes"] == 32, (
        f"conservative estimate should be 32, got {fetched['estimated_wait_minutes']}")


def test_wait_estimate_optimistic_for_reserved_uses_extra_server():
    """PRD §3.2: "The optimistic variant is surfaced only when fetching a
    still-RESERVED online reservation that has not yet arrived: it assumes one
    extra fast-track server, dividing the work-ahead total by the effective-server
    count plus one before rounding up, which yields an estimate at or below the
    conservative figure for the same queue state whenever there is at least one
    effective server."

    Design: Difficulty/dual_variant_calc/wait_estimate_optimistic_vs_conservative_diverges
    """
    clinic = create_clinic(name="WaitClinic", exam_room_capacity=4)
    create_provider(clinic["id"], full_name="Solo", credential="NP", on_shift=True)
    q3 = create_walk_in(clinic["id"], chief_complaint="ahead-esi3")
    triage(clinic["id"], q3["id"], esi_level=3)
    q4 = create_walk_in(clinic["id"], chief_complaint="ahead-esi4")
    triage(clinic["id"], q4["id"], esi_level=4)
    qt = create_walk_in(clinic["id"], chief_complaint="under-test-esi5")
    triage(clinic["id"], qt["id"], esi_level=5)
    qo = create_online_reservation(clinic["id"], chief_complaint="online-hold-esi5")

    fetched = validate_success(api_client.get_queue_entry(qo["id"], _PATIENT), 200)
    # Ahead-set for the RESERVED entry = ESI3 (20) + ESI4 (12) + ESI5 (8) = 40;
    # optimistic divides by effective_servers+1 = 2: ceil(40/2) = 20.
    assert fetched["estimated_wait_minutes"] == 20, (
        f"optimistic estimate should be 20, got {fetched['estimated_wait_minutes']}")


def test_wait_estimate_conservative_exceeds_optimistic():
    """PRD §3.2: the optimistic variant "yields an estimate at or below the
    conservative figure for the same queue state whenever there is at least one
    effective server."

    Design: Difficulty/dual_variant_calc/wait_estimate_optimistic_vs_conservative_diverges
    """
    clinic = create_clinic(name="WaitClinic", exam_room_capacity=4)
    create_provider(clinic["id"], full_name="Solo", credential="NP", on_shift=True)
    q3 = create_walk_in(clinic["id"], chief_complaint="ahead-esi3")
    triage(clinic["id"], q3["id"], esi_level=3)
    q4 = create_walk_in(clinic["id"], chief_complaint="ahead-esi4")
    triage(clinic["id"], q4["id"], esi_level=4)
    qt = create_walk_in(clinic["id"], chief_complaint="under-test-esi5")
    triage(clinic["id"], qt["id"], esi_level=5)
    qo = create_online_reservation(clinic["id"], chief_complaint="online-hold-esi5")

    conservative = validate_success(api_client.get_queue_entry(qt["id"], _PROVIDER), 200)
    optimistic = validate_success(api_client.get_queue_entry(qo["id"], _PATIENT), 200)
    assert conservative["estimated_wait_minutes"] > optimistic["estimated_wait_minutes"]


# ─── combinatorial_formula / wait_estimate_tiered_esi_nonlinear_division ───

def test_wait_estimate_tiered_esi_minutes_ceil_division():
    """PRD §3.2: "it sums, over the ahead-set, the mean provider minutes for each
    ahead-entry's ESI level, read from the clinic's avg_provider_minutes_per_esi
    map (which maps ESI 1 through 5 to mean minutes, defaulting to 40, 30, 20, 12,
    and 8 minutes respectively). That work-ahead total is divided by the number of
    effective servers and rounded up to the next whole minute."

    Design: Difficulty/combinatorial_formula/wait_estimate_tiered_esi_nonlinear_division
    """
    clinic = create_clinic(name="CombClinic", exam_room_capacity=6)
    create_provider(clinic["id"], full_name="P1", credential="MD", on_shift=True)
    create_provider(clinic["id"], full_name="P2", credential="DO", on_shift=True)
    q2 = create_walk_in(clinic["id"], chief_complaint="esi2")
    triage(clinic["id"], q2["id"], esi_level=2)
    q3 = create_walk_in(clinic["id"], chief_complaint="esi3")
    triage(clinic["id"], q3["id"], esi_level=3)
    q4 = create_walk_in(clinic["id"], chief_complaint="esi4")
    triage(clinic["id"], q4["id"], esi_level=4)
    qt = create_walk_in(clinic["id"], chief_complaint="under-test")
    triage(clinic["id"], qt["id"], esi_level=5)

    fetched = validate_success(api_client.get_queue_entry(qt["id"], _PROVIDER), 200)
    # Ahead-set = 30 (ESI2) + 20 (ESI3) + 12 (ESI4) = 62; two servers: ceil(62/2) = 31.
    assert fetched["estimated_wait_minutes"] == 31, (
        f"tiered-ESI ceil division should give 31, got {fetched['estimated_wait_minutes']}")


def test_wait_estimate_front_of_line_is_zero():
    """PRD §3.2: "An entry that is itself rank 1, with no one ahead, estimates 0
    minutes."

    Design: Difficulty/combinatorial_formula/wait_estimate_tiered_esi_nonlinear_division
    """
    clinic = create_clinic(name="CombClinic", exam_room_capacity=6)
    create_provider(clinic["id"], full_name="P1", credential="MD", on_shift=True)
    q2 = create_walk_in(clinic["id"], chief_complaint="front-esi2")
    front = triage(clinic["id"], q2["id"], esi_level=2)

    fetched = validate_success(api_client.get_queue_entry(front["id"], _PROVIDER), 200)
    assert fetched["estimated_wait_minutes"] == 0, (
        f"rank-1 entry with no one ahead should estimate 0, "
        f"got {fetched['estimated_wait_minutes']}")
