"""Test principals for the five roles, and the header builders that mint them.

Four of the five roles are operational identities rather than persisted rows:
``PlantScheduler``, ``PlantOperator``, ``QualityManager`` and ``FacilityAdmin``
all carry an opaque ``X-User-ID`` the server records but never resolves.  Their
identifiers are still meaningful, because two of them are compared across
requests: the operator who signed a CCP record may not adjudicate the deviation
that record raised, and a quality manager who adjudicated a deviation may not
release a pallet the same cycle put on hold.  Hence three distinct quality
managers and two distinct operators.

``Customer`` is the one entity-backed role: its ``X-User-ID`` is the ``id`` of a
persisted ``Customer`` row, so a customer's headers can only be built once that
row exists.  That is what ``make_customer_headers`` is for, and it is the only
correct way to act as a customer on an ownership-gated call.
"""

from prd_bench_local_runner.testing import build_user_headers

ALL_ROLE_NAMES = [
    "Customer",
    "PlantScheduler",
    "PlantOperator",
    "QualityManager",
    "FacilityAdmin",
]


def make_customer_headers(customer_id: str) -> dict:
    """Headers for the brand owner whose ``Customer`` row has id ``customer_id``.

    Ownership checks compare the resource's customer foreign key to this value,
    following the reference chain where necessary: a qualification and a contract
    carry ``customer_id`` directly, a pallet carries ``customer_id``, a load
    reaches its customer through the pallet it draws from, and a chargeback line
    carries ``customer_id``.  Every customer-facing call — opening, submitting and
    superseding a qualification, and reading a qualification, contract, pallet,
    load, cycle, deviation or chargeback line — must use these headers.
    """
    return build_user_headers(customer_id, "Customer")


def make_facility_admin_headers(user_id: str = "fa-root-01") -> dict:
    """Headers for an opaque facility administrator identifier.

    Recorded as ``waived_by_user_id`` when a chargeback line is waived, and never
    matched against an entity ``id``.
    """
    return build_user_headers(user_id, "FacilityAdmin")


def make_plant_scheduler_headers(user_id: str = "sched-nina") -> dict:
    """Headers for an opaque scheduler identifier the server never resolves."""
    return build_user_headers(user_id, "PlantScheduler")


def make_plant_operator_headers(user_id: str = "op_bob") -> dict:
    """Headers for an opaque operator identifier.

    A chamber run's control-point record stores the signing operator as
    ``logged_by_user_id``, and that value is what the segregation-of-duties rule
    compares an adjudicating manager against.
    """
    return build_user_headers(user_id, "PlantOperator")


def make_quality_manager_headers(user_id: str = "qm_alice") -> dict:
    """Headers for an opaque quality-manager identifier.

    Recorded as ``recorded_by_user_id`` on a lab validation run, as
    ``adjudicated_by_user_id`` on a deviation, and as ``released_by_user_id`` on a
    pallet that has been released.
    """
    return build_user_headers(user_id, "QualityManager")


TEST_USERS = {
    # FacilityAdmin — configuration, contracts, waivers and the logical clock.
    "facility_admin_headers": make_facility_admin_headers(),
    "facility_admin_other_headers": make_facility_admin_headers("fa-root-02"),
    # PlantScheduler — cycles and load bookings.
    "plant_scheduler_headers": make_plant_scheduler_headers(),
    # PlantOperator — receipts, dock inspections, starts, CCP records, shipping.
    # op_bob signs the control-point records the segregation-of-duties rule keys on.
    "plant_operator_headers": make_plant_operator_headers("op_bob"),
    "plant_operator_second_headers": make_plant_operator_headers("op_ines"),
    # QualityManager — validation runs, decisions, dispositions, adjudications,
    # package inspections and release decisions.  qm_alice adjudicates; qm_carol
    # and qm_dave stand in when four-eyes forbids the adjudicator from releasing.
    "quality_manager_headers": make_quality_manager_headers("qm_alice"),
    "quality_manager_second_headers": make_quality_manager_headers("qm_carol"),
    "quality_manager_third_headers": make_quality_manager_headers("qm_dave"),
    # A Customer identifier that belongs to no persisted row; only ever used in
    # tests that must never pass an ownership check.
    "unrelated_customer_headers": make_customer_headers(
        "00000000-0000-4000-8000-0000000000ff"
    ),
}

# The bare identifiers, for tests that assert a recorded actor.
OPERATOR_BOB = "op_bob"
OPERATOR_INES = "op_ines"
QM_ALICE = "qm_alice"
QM_CAROL = "qm_carol"
QM_DAVE = "qm_dave"
ADMIN_ROOT = "fa-root-01"
SCHEDULER_NINA = "sched-nina"
