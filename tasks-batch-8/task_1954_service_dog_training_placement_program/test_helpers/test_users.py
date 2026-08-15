"""Pre-built role headers for every role in the PRD (§2.1).

ProgramAdmin, IntakeCoordinator, TrainingDirector, Veterinarian are opaque
operator ids: shared constants are canonical. IntakeCoordinator gets two
extra operator ids because the contribution receive segregation-of-duties
rule (PRD §3.3) requires receiver != creator.

Trainer, Evaluator, Applicant, PuppyRaiser are entity-backed: ownership-gated
calls MUST use the make_*_headers(entity_id) builders with the real entity id.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque roles — canonical shared constants.
    "program_admin_headers": build_user_headers("admin-1", "ProgramAdmin"),
    "coordinator_headers": build_user_headers("coord-a", "IntakeCoordinator"),
    "coordinator_b_headers": build_user_headers("coord-b", "IntakeCoordinator"),
    "coordinator_c_headers": build_user_headers("coord-c", "IntakeCoordinator"),
    "training_director_headers": build_user_headers("td-1", "TrainingDirector"),
    "veterinarian_headers": build_user_headers("vet-1", "Veterinarian"),
    # Entity-backed roles — fallback constants ONLY for tests that never
    # exercise an ownership-gated call.
    "trainer_headers": build_user_headers("trainer-fallback", "Trainer"),
    "evaluator_headers": build_user_headers("evaluator-fallback", "Evaluator"),
    "applicant_headers": build_user_headers("applicant-fallback", "Applicant"),
    "puppy_raiser_headers": build_user_headers("raiser-fallback", "PuppyRaiser"),
}


def make_trainer_headers(trainer_id: str) -> dict:
    """Trainer is entity-backed by Trainer: pass the real Trainer.id whenever
    the call is ownership-gated (e.g. milestone recording, support resolve)."""
    return build_user_headers(trainer_id, "Trainer")


def make_evaluator_headers(trainer_id: str) -> dict:
    """Evaluator is entity-backed by Trainer: pass the real Trainer.id of the
    evaluating trainer whenever scoring or recording results."""
    return build_user_headers(trainer_id, "Evaluator")


def make_applicant_headers(applicant_id: str) -> dict:
    """Applicant is entity-backed by Applicant: pass the real Applicant.id
    whenever the call is ownership-gated (resubmit, withdraw, reopen)."""
    return build_user_headers(applicant_id, "Applicant")


def make_puppy_raiser_headers(raiser_id: str) -> dict:
    """PuppyRaiser is entity-backed by PuppyRaiser: pass the real
    PuppyRaiser.id whenever the call is ownership-gated (hiatus, resume,
    early-return)."""
    return build_user_headers(raiser_id, "PuppyRaiser")


def make_coordinator_headers(user_id: str) -> dict:
    """IntakeCoordinator is opaque; distinct user ids matter for the
    contribution receive segregation-of-duties rule (PRD §3.3)."""
    return build_user_headers(user_id, "IntakeCoordinator")
