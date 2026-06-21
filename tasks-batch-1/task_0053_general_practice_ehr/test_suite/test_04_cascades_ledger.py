"""Finalization cascade (depth-3) and the compensating-action invariants on
panel membership and the patient monetary ledger.
"""
from test_helpers import (
    validate_success,
    TEST_USERS,
    set_clock,
    create_provider,
    create_patient,
    create_hedis_measure,
    create_coded_visit,
    create_pcp_bound_patient,
    bind_patient,
    record_payment_payload,
)

FD = TEST_USERS["frontdesk_headers"]
BILLER = TEST_USERS["biller_headers"]


# ─── Queue A: transitive_cascade / finalize_visit_depth3_cascade ───

def test_finalize_physical_visit_recomputes_ledger_and_closes_gap(api):
    """PRD §3.6: "that new total then flows into the patient's lifetime-charge and
    outstanding-balance ledger; and, when the finalized visit is of a qualifying type
    and a matching open care gap exists, the relevant quality measure flips to
    compliant, which in turn forces the patient's open-care-gap count to be recomputed
    downward."
    PRD §3.6: "if the finalized visit's `visit_type` is `PHYSICAL` or `VACCINATION` and
    the patient has a matching HEDIS measure that is still in `GAP` status for the
    current measurement year, that measure's status flips to `NUMERATOR_COMPLIANT`."

    Design: Difficulty/transitive_cascade/finalize_visit_depth3_cascade
    """
    set_clock("2026-06-01T00:00:00Z")
    provider = create_provider(specialty="PEDIATRICS")
    patient = create_patient(first_name="Kid", date_of_birth="2021-01-01", sex="M")
    measure = create_hedis_measure(patient["id"], measure_type="CIS_FLU",
                                   measurement_year=2026, method="ADMINISTRATIVE")
    # PHYSICAL visit, PREVENTIVE base 12000 -> provisional 12000 -> final 10800
    _, _, _, visit = create_coded_visit(
        provider=provider, patient=patient,
        cpt_overrides={"category": "PREVENTIVE", "base_fee_cents": 12000, "requires_em_level": False},
        charge_overrides={"units": 1},
        visit_overrides={"visit_type": "PHYSICAL",
                         "scheduled_start": "2026-06-02T09:00:00Z",
                         "scheduled_end": "2026-06-02T09:30:00Z"},
    )
    finalized = validate_success(api.finalize_visit(visit["id"], BILLER), 200)
    assert finalized["billed_total_cents"] == 10800

    patient_after = validate_success(api.get_patient(patient["id"], FD), 200)
    assert patient_after["lifetime_charges_cents"] == 10800, (
        f"lifetime_charges_cents must include the finalized total 10800, "
        f"got {patient_after['lifetime_charges_cents']}"
    )
    measure_after = validate_success(api.get_hedis_measure(measure["id"], FD), 200)
    assert measure_after["status"] == "NUMERATOR_COMPLIANT"


def test_finalize_physical_visit_recomputes_open_care_gaps_downward(api):
    """PRD §3.6: "Fourth, that flip causes the patient's `open_care_gaps` count to be
    recomputed downward."

    Design: Difficulty/transitive_cascade/finalize_visit_depth3_cascade
    """
    set_clock("2026-06-01T00:00:00Z")
    provider = create_provider(specialty="PEDIATRICS")
    patient = create_patient(first_name="Kid", date_of_birth="2021-01-01", sex="M")
    create_hedis_measure(patient["id"], measure_type="CIS_FLU",
                         measurement_year=2026, method="ADMINISTRATIVE")
    before = validate_success(api.get_patient(patient["id"], FD), 200)
    assert before["open_care_gaps"] == 1, (
        f"patient should start with 1 open eligible CIS_FLU gap, got {before['open_care_gaps']}"
    )
    _, _, _, visit = create_coded_visit(
        provider=provider, patient=patient,
        cpt_overrides={"category": "PREVENTIVE", "base_fee_cents": 12000, "requires_em_level": False},
        charge_overrides={"units": 1},
        visit_overrides={"visit_type": "PHYSICAL",
                         "scheduled_start": "2026-06-02T09:00:00Z",
                         "scheduled_end": "2026-06-02T09:30:00Z"},
    )
    validate_success(api.finalize_visit(visit["id"], BILLER), 200)
    after = validate_success(api.get_patient(patient["id"], FD), 200)
    assert after["open_care_gaps"] == 0, (
        f"open_care_gaps must recompute from 1 to 0 after the gap closes, got {after['open_care_gaps']}"
    )


# ─── Queue A: compensating_invariant / patient_balance_conserved_on_finalize_then_payment ───

def test_outstanding_balance_set_by_finalize(api):
    """PRD §3.6: "Second, the patient's `lifetime_charges_cents` and
    `outstanding_balance_cents` are recomputed so that they now include this visit's
    billed total — lifetime charges resum across the patient's finalized visits, and
    outstanding balance is lifetime charges minus recorded payments."

    Design: Difficulty/compensating_invariant/patient_balance_conserved_on_finalize_then_payment
    """
    provider = create_provider()
    patient = create_patient()
    _, _, _, visit = create_coded_visit(
        provider=provider, patient=patient,
        cpt_overrides={"category": "PREVENTIVE", "base_fee_cents": 12000, "requires_em_level": False},
        charge_overrides={"units": 1},
        visit_overrides={"visit_type": "PHYSICAL",
                         "scheduled_start": "2026-06-01T16:00:00Z",
                         "scheduled_end": "2026-06-01T16:30:00Z"},
    )
    validate_success(api.finalize_visit(visit["id"], BILLER), 200)
    after_finalize = validate_success(api.get_patient(patient["id"], FD), 200)
    assert after_finalize["outstanding_balance_cents"] == 10800, (
        f"outstanding balance after finalize must be 10800, got {after_finalize['outstanding_balance_cents']}"
    )


def test_payment_compensates_balance_to_zero(api):
    """PRD §3.2: "`outstanding_balance_cents` is `lifetime_charges_cents` minus the
    total of all payments recorded for the patient; it may go negative if the patient
    has overpaid, representing a credit."

    Design: Difficulty/compensating_invariant/patient_balance_conserved_on_finalize_then_payment
    """
    provider = create_provider()
    patient = create_patient()
    _, _, _, visit = create_coded_visit(
        provider=provider, patient=patient,
        cpt_overrides={"category": "PREVENTIVE", "base_fee_cents": 12000, "requires_em_level": False},
        charge_overrides={"units": 1},
        visit_overrides={"visit_type": "PHYSICAL",
                         "scheduled_start": "2026-06-01T16:00:00Z",
                         "scheduled_end": "2026-06-01T16:30:00Z"},
    )
    validate_success(api.finalize_visit(visit["id"], BILLER), 200)
    paid = validate_success(
        api.record_payment(patient["id"], record_payment_payload(10800), BILLER), 200
    )
    assert paid["outstanding_balance_cents"] == 0, (
        f"a 10800 payment must drive outstanding balance to 0, got {paid['outstanding_balance_cents']}"
    )


# ─── Queue A: compensating_invariant / panel_membership_conserved_on_bind_then_deactivate ───

def test_panel_size_increments_on_second_bind(api):
    """PRD §3.1: "A provider's `panel_size` is a derived count: the number of patients
    whose bound primary-care provider is this provider and whose own status is
    `ACTIVE`."

    Design: Difficulty/compensating_invariant/panel_membership_conserved_on_bind_then_deactivate
    """
    provider, patient1 = create_pcp_bound_patient(provider_overrides={"panel_capacity": 5})
    assert provider["panel_size"] == 1
    patient2 = create_patient(sex="F")
    provider_after = bind_patient(provider["id"], patient2["id"], provider["version"])
    assert provider_after["panel_size"] == 2, (
        f"second bind must raise panel_size to 2, got {provider_after['panel_size']}"
    )


def test_panel_size_compensated_on_patient_deactivate(api):
    """PRD §3.2: "if the patient had a bound PCP, that former provider's `panel_size`
    is recomputed (decremented by one as this patient leaves the active panel)."

    Design: Difficulty/compensating_invariant/panel_membership_conserved_on_bind_then_deactivate
    """
    provider, patient1 = create_pcp_bound_patient(provider_overrides={"panel_capacity": 5})
    patient2 = create_patient(sex="F")
    provider_after = bind_patient(provider["id"], patient2["id"], provider["version"])
    assert provider_after["panel_size"] == 2
    validate_success(api.deactivate_patient(patient2["id"], FD), 200)
    refreshed = validate_success(api.get_provider(provider["id"], FD), 200)
    assert refreshed["panel_size"] == 1, (
        f"deactivating the second patient must restore panel_size to 1, got {refreshed['panel_size']}"
    )
