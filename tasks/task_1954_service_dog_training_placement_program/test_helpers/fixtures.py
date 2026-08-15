"""Composite setup helpers (PRD §3 workflows).

Every helper builds preconditions from scratch against a fresh server using
only PRD-declared endpoints, and uses the lenient get_success_data() so a
setup failure surfaces as a clear "Setup failed" message.

Canonical pipeline stages (PRD §3.1–§3.8):
  applicant intake -> review -> FINALIZED_ACCEPTED assessment -> approve
    -> WaitlistEntry PENDING -> (contributions received) -> ELIGIBLE
  dog intake -> begin-screening -> screening submit (CLEARED)
    -> raiser placement -> placement complete (IN_ADVANCED_TRAINING)
    -> 6 advancing milestones -> MATCH_READY
  match proposal + accept -> class create/open -> enroll -> clock -> start
    -> attendance -> PAT pass -> clock -> graduation review -> graduate
    -> Partnership ACTIVE with 3 auto follow-ups
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    ADVANCING_MILESTONES,
    PAT_PERFECT_SCORES,
)
from .factories import (
    create_applicant_payload,
    create_assessment_payload,
    create_class_payload,
    create_contribution_payload,
    create_dog_payload,
    create_puppy_raiser_payload,
    create_screening_payload,
    create_trainer_payload,
)
from .test_users import TEST_USERS, make_evaluator_headers, make_trainer_headers

ADMIN = TEST_USERS["program_admin_headers"]
COORD = TEST_USERS["coordinator_headers"]
COORD_B = TEST_USERS["coordinator_b_headers"]
TD = TEST_USERS["training_director_headers"]
VET = TEST_USERS["veterinarian_headers"]


def _fail(ctx, resp):
    raise AssertionError(
        f"Setup failed at {ctx}: HTTP {resp.status_code} {resp.text[:400]}"
    )


def _ok(ctx, resp, status=None):
    data = get_success_data(resp)
    if status is not None and resp.status_code != status:
        _fail(ctx, resp)
    return data


# ---------------------------------------------------------------------------
# Applicant pipeline (PRD §3.1, §3.2)
# ---------------------------------------------------------------------------

def create_applicant_with_accepted_assessment(
    track="MOBILITY",
    income_cents=12_000_000,
    region="NW",
    required_tasks=("RETRIEVE_ITEMS",),
    urgency="STANDARD",
    home_score=6,
):
    """Applicant in IN_REVIEW with one FINALIZED_ACCEPTED assessment.

    Returns (applicant, assessment).
    """
    applicant = _ok(
        "create applicant",
        api_client.create_applicant(
            create_applicant_payload(
                placement_track=track,
                household_income_cents=income_cents,
                region=region,
            ),
            COORD,
        ),
        201,
    )
    _ok("begin review", api_client.begin_review(applicant["id"], COORD))
    assessment = _ok(
        "create assessment",
        api_client.create_assessment(
            applicant["id"],
            create_assessment_payload(
                required_tasks=list(required_tasks),
                task_urgency_tier=urgency,
                home_environment_score=home_score,
            ),
            COORD,
        ),
        201,
    )
    _ok(
        "finalize assessment",
        api_client.finalize_assessment(
            assessment["id"], {"outcome": "FINALIZED_ACCEPTED"}, COORD
        ),
    )
    applicant = _ok("reload applicant", api_client.get_applicant(applicant["id"], COORD))
    return applicant, assessment


def create_waitlisted_applicant(**kwargs):
    """Applicant WAITLISTED with a PENDING entry. Returns (applicant, entry)."""
    applicant, _assessment = create_applicant_with_accepted_assessment(**kwargs)
    applicant = _ok("approve", api_client.approve_applicant(applicant["id"], COORD))
    entries = _ok(
        "list entries", api_client.list_applicant_waitlist_entries(applicant["id"], COORD)
    )
    assert isinstance(entries, list) and len(entries) == 1, (
        "Setup failed: approve must create exactly one waitlist entry"
    )
    return applicant, entries[0]


def create_eligible_entry(
    contribution_cents=None,
    creator=None,
    receiver=None,
    **kwargs,
):
    """Applicant + entry flipped to ELIGIBLE via one received contribution.

    Defaults target the MOBILITY zero-credit provisional requirement
    (1,350,000). Returns (applicant, entry, contribution).
    """
    applicant, entry = create_waitlisted_applicant(**kwargs)
    amount = contribution_cents
    if amount is None:
        amount = entry["effective_requirement_cents"]
    creator_h = creator or COORD
    receiver_h = receiver or COORD_B
    contribution = _ok(
        "create contribution",
        api_client.create_contribution(
            applicant["id"],
            create_contribution_payload(amount_cents=amount),
            creator_h,
        ),
        201,
    )
    contribution = _ok(
        "receive contribution",
        api_client.receive_contribution(contribution["id"], receiver_h),
    )
    entry = _ok("reload entry", api_client.get_waitlist_entry(entry["id"], COORD))
    applicant = _ok("reload applicant", api_client.get_applicant(applicant["id"], COORD))
    assert entry["status"] == "ELIGIBLE", (
        f"Setup failed: entry must be ELIGIBLE after funding, got {entry['status']}"
    )
    return applicant, entry, contribution


# ---------------------------------------------------------------------------
# Dog pipeline (PRD §3.4–§3.6)
# ---------------------------------------------------------------------------

def create_cleared_dog(dog_overrides=None, screening_overrides=None):
    """DONATED dog CLEARED via the canonical 84-point screening."""
    dog = _ok(
        "create dog",
        api_client.create_dog(create_dog_payload(**(dog_overrides or {})), ADMIN),
        201,
    )
    _ok("begin screening", api_client.begin_screening(dog["id"], VET))
    screening = _ok(
        "create screening",
        api_client.create_screening(
            dog["id"],
            create_screening_payload(**(screening_overrides or {})),
            VET,
        ),
        201,
    )
    _ok("submit screening", api_client.submit_screening(screening["id"], VET))
    dog = _ok("reload dog", api_client.get_dog(dog["id"], TD))
    assert dog["status"] == "CLEARED", (
        f"Setup failed: dog must be CLEARED, got {dog['status']}"
    )
    return dog


def create_approved_raiser(**overrides):
    """Puppy raiser walked APPLIED -> VETTED -> APPROVED."""
    raiser = _ok(
        "create raiser",
        api_client.create_puppy_raiser(create_puppy_raiser_payload(**overrides), ADMIN),
        201,
    )
    _ok("vet raiser", api_client.vet_raiser(raiser["id"], ADMIN))
    raiser = _ok("approve raiser", api_client.approve_raiser(raiser["id"], ADMIN))
    return raiser


def create_certified_trainer(pat_certified=False):
    """Trainer walked PROBATION -> CERTIFIED."""
    trainer = _ok(
        "create trainer",
        api_client.create_trainer(
            create_trainer_payload(pat_certified=pat_certified), ADMIN
        ),
        201,
    )
    trainer = _ok("certify trainer", api_client.certify_trainer(trainer["id"], ADMIN))
    return trainer


def create_dog_in_advanced_training(raiser=None, trainer=None, dog_overrides=None):
    """CLEARED dog placed with a raiser, placement completed with a certified
    primary trainer -> dog IN_ADVANCED_TRAINING.

    Returns (dog, raiser, trainer, placement).
    """
    dog = create_cleared_dog(dog_overrides=dog_overrides)
    if raiser is None:
        raiser = create_approved_raiser(region=dog["region"])
    if trainer is None:
        trainer = create_certified_trainer()
    placement = _ok(
        "create placement",
        api_client.create_raiser_placement(
            dog["id"], {"puppy_raiser_id": raiser["id"]}, TD
        ),
        201,
    )
    _ok(
        "complete placement",
        api_client.complete_raiser_placement(
            placement["id"], {"primary_trainer_id": trainer["id"]}, TD
        ),
    )
    dog = _ok("reload dog", api_client.get_dog(dog["id"], TD))
    assert dog["status"] == "IN_ADVANCED_TRAINING", (
        f"Setup failed: dog must be IN_ADVANCED_TRAINING, got {dog['status']}"
    )
    raiser = _ok("reload raiser", api_client.get_puppy_raiser(raiser["id"], ADMIN))
    return dog, raiser, trainer, placement


def record_milestone(dog_id, trainer_id, category, score, task_code=None):
    """Record one milestone as the dog's primary trainer (PRD §3.6)."""
    payload = {"category": category, "score": score}
    if task_code is not None:
        payload["task_code"] = task_code
    return _ok(
        "record milestone",
        api_client.create_milestone(
            dog_id, payload, make_trainer_headers(trainer_id)
        ),
        201,
    )


def create_match_ready_dog(raiser=None, trainer=None, dog_overrides=None,
                           milestones=None):
    """Dog walked to MATCH_READY via the canonical advancing milestone set.

    Returns (dog, raiser, trainer).
    """
    dog, raiser, trainer, _placement = create_dog_in_advanced_training(
        raiser=raiser, trainer=trainer, dog_overrides=dog_overrides
    )
    for spec in (milestones or ADVANCING_MILESTONES):
        record_milestone(
            dog["id"],
            trainer["id"],
            spec["category"],
            spec["score"],
            spec.get("task_code"),
        )
    dog = _ok("reload dog", api_client.get_dog(dog["id"], TD))
    assert dog["status"] == "MATCH_READY", (
        f"Setup failed: dog must be MATCH_READY after milestones, got {dog['status']}"
    )
    return dog, raiser, trainer


# ---------------------------------------------------------------------------
# Match + class + enrollment pipeline (PRD §3.7)
# ---------------------------------------------------------------------------

def propose_and_accept_match(dog, entry):
    """Explicit proposal + accept. Returns the ACCEPTED MatchRecord."""
    dog = _ok("read dog version", api_client.get_dog(dog["id"], TD))
    match = _ok(
        "propose match",
        api_client.create_match_proposal(
            dog["id"],
            {
                "waitlist_entry_id": entry["id"],
                "expected_dog_version": dog["version"],
            },
            COORD,
        ),
        201,
    )
    match = _ok("accept match", api_client.accept_match(match["id"], COORD))
    assert match["status"] == "ACCEPTED", (
        f"Setup failed: match must be ACCEPTED, got {match['status']}"
    )
    return match


def create_class_enrolling(lead_trainer_id, **overrides):
    """Class created and moved PLANNED -> ENROLLING. Returns the class."""
    clazz = _ok(
        "create class",
        api_client.create_class(
            create_class_payload(lead_trainer_id=lead_trainer_id, **overrides), TD
        ),
        201,
    )
    clazz = _ok("open enrollment", api_client.open_enrollment(clazz["id"], TD))
    return clazz


def enroll_match(clazz, match):
    """Enroll an ACCEPTED match with a fresh OCC version. Returns enrollment."""
    clazz = _ok("read class version", api_client.get_class(clazz["id"], TD))
    enrollment = _ok(
        "create enrollment",
        api_client.create_enrollment(
            clazz["id"],
            {"match_id": match["id"], "expected_class_version": clazz["version"]},
            TD,
        ),
        201,
    )
    return enrollment


def setup_enrolled_pair(
    required_tasks=("RETRIEVE_ITEMS",),
    dog_overrides=None,
    milestones=None,
    class_overrides=None,
    contribution_cents=None,
    applicant_kwargs=None,
):
    """Full pipeline: MATCH_READY dog + ELIGIBLE entry -> ACCEPTED match ->
    ENROLLING class -> ENROLLED enrollment.

    Returns dict with keys: dog, raiser, trainer, applicant, entry, match,
    clazz, enrollment.
    """
    dog, raiser, trainer = create_match_ready_dog(
        dog_overrides=dog_overrides, milestones=milestones
    )
    ak = {"track": "MOBILITY", "income_cents": 12_000_000, "required_tasks": tuple(required_tasks)}
    ak.update(applicant_kwargs or {})
    applicant, entry, _contribution = create_eligible_entry(
        contribution_cents=contribution_cents, **ak
    )
    match = propose_and_accept_match(dog, entry)
    clazz = create_class_enrolling(trainer["id"], **(class_overrides or {}))
    enrollment = enroll_match(clazz, match)
    clazz = _ok("reload class", api_client.get_class(clazz["id"], TD))
    return {
        "dog": _ok("reload dog", api_client.get_dog(dog["id"], TD)),
        "raiser": raiser,
        "trainer": trainer,
        "applicant": _ok("reload applicant", api_client.get_applicant(applicant["id"], COORD)),
        "entry": _ok("reload entry", api_client.get_waitlist_entry(entry["id"], COORD)),
        "match": match,
        "clazz": clazz,
        "enrollment": enrollment,
    }


def start_class_in_session(clazz):
    """Advance the clock to the class's starts_on and start the class."""
    _ok(
        "clock to starts_on",
        api_client.set_clock(
            {"to_iso8601": f"{clazz['starts_on']}T00:00:00Z"}, ADMIN
        ),
    )
    clazz = _ok("start class", api_client.start_class(clazz["id"], TD))
    assert clazz["status"] == "IN_SESSION", (
        f"Setup failed: class must be IN_SESSION, got {clazz['status']}"
    )
    return clazz


def setup_in_session_enrollment(attendance=None, pat_evaluator=None,
                                 pat_scores=None, pat_time="2026-10-10T10:00:00Z",
                                 **kwargs):
    """Enrolled pair whose class is IN_SESSION. Optionally records attendance
    and/or schedules+scores a passing PAT with a dedicated evaluator.

    Returns the setup dict with optional keys 'evaluator' and 'pat'.
    """
    ctx = setup_enrolled_pair(**kwargs)
    ctx["clazz"] = start_class_in_session(ctx["clazz"])
    if attendance is not None:
        ctx["enrollment"] = _ok(
            "record attendance",
            api_client.record_attendance(
                ctx["enrollment"]["id"], {"sessions_attended": attendance}, TD
            ),
        )
    if pat_scores is not None or pat_evaluator is not None:
        evaluator = pat_evaluator or create_certified_trainer(pat_certified=True)
        ctx["evaluator"] = evaluator
        pat = _ok(
            "schedule PAT",
            api_client.create_pat(
                ctx["enrollment"]["id"],
                {"scheduled_at": pat_time},
                make_evaluator_headers(evaluator["id"]),
            ),
            201,
        )
        ctx["pat"] = pat
        if pat_scores is not None:
            ctx["pat"] = _ok(
                "score PAT",
                api_client.score_pat(
                    pat["id"],
                    {"exercise_scores": pat_scores},
                    make_evaluator_headers(evaluator["id"]),
                ),
            )
    return ctx


def setup_graduated_partnership(attendance=20, **kwargs):
    """Full lifecycle through graduation. Partnership ACTIVE with 3 auto
    follow-ups; dog and applicant PLACED.

    Returns the setup dict with keys 'partnership' and 'evaluator' added.
    """
    ctx = setup_in_session_enrollment(
        attendance=attendance, pat_scores=PAT_PERFECT_SCORES, **kwargs
    )
    _ok(
        "clock past ends_on",
        api_client.set_clock({"to_iso8601": "2026-10-16T00:00:00Z"}, ADMIN),
    )
    clazz = _ok(
        "begin graduation review",
        api_client.begin_graduation_review(ctx["clazz"]["id"], TD),
    )
    ctx["clazz"] = clazz
    partnership = _ok(
        "graduate",
        api_client.graduate_enrollment(ctx["enrollment"]["id"], TD),
        201,
    )
    ctx["partnership"] = partnership
    ctx["enrollment"] = _ok(
        "reload enrollment", api_client.get_enrollment(ctx["enrollment"]["id"], TD)
    )
    ctx["dog"] = _ok("reload dog", api_client.get_dog(ctx["dog"]["id"], TD))
    ctx["applicant"] = _ok(
        "reload applicant", api_client.get_applicant(ctx["applicant"]["id"], COORD)
    )
    assert ctx["enrollment"]["status"] == "GRADUATED", (
        f"Setup failed: enrollment must be GRADUATED, got {ctx['enrollment']['status']}"
    )
    return ctx
