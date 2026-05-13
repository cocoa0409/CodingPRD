"""Paper composition (deterministic, per-candidate, archived) per PRD §3.3."""
import hashlib

import db
from errors import err
from services.util import canonical_json


OBJECTIVE_TYPES = {"SINGLE_CHOICE", "MULTI_CHOICE", "TRUE_FALSE"}
SUBJECTIVE_TYPES = {"SHORT_ANSWER", "ESSAY"}


def _seed_uint64(seed_input: str) -> int:
    """First 16 hex chars of SHA-256, interpreted as a uint64."""
    digest = hashlib.sha256(seed_input.encode("utf-8")).hexdigest()
    return int(digest[:16], 16)


def _seeded_shuffle(seq, seed: int) -> list:
    """Fisher–Yates shuffle in-place over a copy of seq using a Linear Congruential
    Generator seeded by `seed` (deterministic, no floats, no `random` module reseed
    state to worry about). Returns the shuffled list."""
    arr = list(seq)
    # LCG parameters (Numerical Recipes); well-spread for n up to a few thousand.
    state = seed & 0xFFFFFFFFFFFFFFFF
    if state == 0:
        state = 0x9E3779B97F4A7C15  # avoid zero state
    # Fisher–Yates from end to start
    n = len(arr)
    for i in range(n - 1, 0, -1):
        # advance LCG
        state = (state * 6364136223846793005 + 1442695040888963407) & 0xFFFFFFFFFFFFFFFF
        # use top bits of state to choose j in [0, i] inclusive
        j = (state >> 33) % (i + 1)
        arr[i], arr[j] = arr[j], arr[i]
    return arr


def _select_random(exam_id: str, target_count: int, seed: int) -> list:
    pool = [q for q in db.questions.values() if q.get("exam_id") == exam_id]
    pool.sort(key=lambda q: q["_seq"])
    if len(pool) < target_count:
        raise err("ERR_SAMPLING_INFEASIBLE", "RANDOM: pool smaller than target_count")
    shuffled = _seeded_shuffle(pool, seed)
    return shuffled[:target_count]


def _select_stratified(exam_id: str, spec: dict, seed: int) -> list:
    buckets = spec.get("difficulty_buckets") or {}
    ordered = ["EASY", "MEDIUM", "HARD"]
    out = []
    for idx, diff in enumerate(ordered):
        want = int(buckets.get(diff, 0) or 0)
        eligible = [q for q in db.questions.values()
                    if q.get("exam_id") == exam_id and q.get("difficulty") == diff]
        eligible.sort(key=lambda q: q["_seq"])
        if len(eligible) < want:
            raise err("ERR_SAMPLING_INFEASIBLE",
                      f"STRATIFIED: bucket {diff} short")
        if want <= 0:
            continue
        bucket_seed = (seed + idx + 1) & 0xFFFFFFFFFFFFFFFF
        shuffled = _seeded_shuffle(eligible, bucket_seed)
        out.extend(shuffled[:want])
    return out


def _select_blueprint(exam_id: str, spec: dict, seed: int) -> list:
    slots = spec.get("slots") or []
    out = []
    for idx, slot in enumerate(slots):
        topic = slot.get("topic")
        qtype = slot.get("question_type")
        diff = slot.get("difficulty")
        want = int(slot.get("count", 0) or 0)
        eligible = [q for q in db.questions.values()
                    if q.get("exam_id") == exam_id
                    and q.get("topic") == topic
                    and q.get("question_type") == qtype
                    and q.get("difficulty") == diff]
        eligible.sort(key=lambda q: q["_seq"])
        if len(eligible) < want:
            raise err("ERR_SAMPLING_INFEASIBLE",
                      f"BLUEPRINT: slot {idx} short")
        if want <= 0:
            continue
        slot_seed = (seed + (idx + 1) * 0x9E3779B97F4A7C15) & 0xFFFFFFFFFFFFFFFF
        shuffled = _seeded_shuffle(eligible, slot_seed)
        out.extend(shuffled[:want])
    return out


def check_sampling_feasibility(exam: dict) -> None:
    """Run the same selection as compose_paper but discard the output —
    used during DRAFT → OPEN_REGISTRATION to verify feasibility."""
    rule = exam.get("sampling_rule_type")
    spec = exam.get("sampling_rule_spec") or {}
    # Use a fixed seed for the dry run; we only care whether each branch can be
    # satisfied at all (it depends on pool sizes, not seed).
    seed = 1
    exam_id = exam["id"]
    if rule == "RANDOM":
        target = int(spec.get("target_count", 0) or 0)
        pool = [q for q in db.questions.values() if q.get("exam_id") == exam_id]
        if len(pool) < target:
            raise err("ERR_SAMPLING_INFEASIBLE", "RANDOM: pool smaller than target_count")
    elif rule == "STRATIFIED":
        buckets = spec.get("difficulty_buckets") or {}
        for diff in ["EASY", "MEDIUM", "HARD"]:
            want = int(buckets.get(diff, 0) or 0)
            eligible = [q for q in db.questions.values()
                        if q.get("exam_id") == exam_id and q.get("difficulty") == diff]
            if len(eligible) < want:
                raise err("ERR_SAMPLING_INFEASIBLE",
                          f"STRATIFIED: bucket {diff} short")
    elif rule == "BLUEPRINT":
        slots = spec.get("slots") or []
        for idx, slot in enumerate(slots):
            want = int(slot.get("count", 0) or 0)
            eligible = [q for q in db.questions.values()
                        if q.get("exam_id") == exam_id
                        and q.get("topic") == slot.get("topic")
                        and q.get("question_type") == slot.get("question_type")
                        and q.get("difficulty") == slot.get("difficulty")]
            if len(eligible) < want:
                raise err("ERR_SAMPLING_INFEASIBLE",
                          f"BLUEPRINT: slot {idx} short")
    else:
        raise err("ERR_SAMPLING_INFEASIBLE", f"Unknown sampling_rule_type {rule!r}")
    # Silence unused
    _ = seed


def compose_paper(exam: dict, attempt: dict) -> tuple[list, dict, str]:
    """Run the deterministic paper composition. Returns
    (paper_question_ids, paper_option_order, paper_version_hash)."""
    rule = exam.get("sampling_rule_type")
    spec = exam.get("sampling_rule_spec") or {}
    seed = _seed_uint64(attempt["id"])
    if rule == "RANDOM":
        target = int(spec.get("target_count", 0) or 0)
        selected = _select_random(exam["id"], target, seed)
    elif rule == "STRATIFIED":
        selected = _select_stratified(exam["id"], spec, seed)
    elif rule == "BLUEPRINT":
        selected = _select_blueprint(exam["id"], spec, seed)
    else:
        raise err("ERR_SAMPLING_INFEASIBLE", f"Unknown sampling_rule_type {rule!r}")

    paper_question_ids = [q["id"] for q in selected]

    # Option shuffling
    paper_option_order = {}
    for q in selected:
        if q["question_type"] in ("SINGLE_CHOICE", "MULTI_CHOICE"):
            opts = q.get("options") or []
            keys = [o.get("option_key") for o in opts]
            if exam.get("option_shuffle"):
                qseed = _seed_uint64(attempt["id"] + q["id"])
                keys = _seeded_shuffle(keys, qseed)
            paper_option_order[q["id"]] = keys

    # paper_version_hash
    payload = {
        "ids": paper_question_ids,
        "opts": paper_option_order,
        "exam_version": int(exam.get("version", 1)),
    }
    paper_version_hash = hashlib.sha256(
        canonical_json(payload).encode("utf-8")
    ).hexdigest()

    return paper_question_ids, paper_option_order, paper_version_hash
