"""Entity graph navigation helpers."""

from db import db, ordered
from errors import ApiError

LIVE_STAGES = ("PROJECTED", "ROUGH_IN_VERIFIED", "CONFIRMED", "REGISTERED")
UNRESOLVED_CA_STATUSES = ("OPEN", "SUBMITTED", "REJECTED", "ESCALATED")
OPEN_COUNTED_CA_STATUSES = ("OPEN", "SUBMITTED", "ESCALATED")


def require(collection, entity_id, error_id):
    row = collection.get(entity_id)
    if row is None:
        raise ApiError(error_id)
    return row


def require_builder(builder_id):
    return require(db.builders, builder_id, "ERR_BUILDER_NOT_FOUND")


def require_subdivision(subdivision_id):
    return require(db.subdivisions, subdivision_id, "ERR_SUBDIVISION_NOT_FOUND")


def require_plan_model(plan_model_id):
    return require(db.plan_models, plan_model_id, "ERR_PLAN_MODEL_NOT_FOUND")


def require_home(home_id):
    return require(db.homes, home_id, "ERR_HOME_NOT_FOUND")


def require_rater(rater_id):
    return require(db.raters, rater_id, "ERR_RATER_NOT_FOUND")


def require_rating(rating_id):
    return require(db.ratings, rating_id, "ERR_RATING_NOT_FOUND")


def require_inspection(inspection_id):
    return require(db.inspections, inspection_id, "ERR_INSPECTION_NOT_FOUND")


def require_sample_set(sample_set_id):
    return require(db.sample_sets, sample_set_id, "ERR_SAMPLE_SET_NOT_FOUND")


def require_qa_review(qa_review_id):
    return require(db.qa_reviews, qa_review_id, "ERR_QA_REVIEW_NOT_FOUND")


def require_corrective_action(action_id):
    return require(db.corrective_actions, action_id, "ERR_CORRECTIVE_ACTION_NOT_FOUND")


def require_document_package(package_id):
    return require(db.document_packages, package_id, "ERR_DOCUMENT_PACKAGE_NOT_FOUND")


# --- navigation -----------------------------------------------------------
def subdivision_of_home(home):
    return db.subdivisions.get(home["subdivision_id"])


def builder_of_subdivision(subdivision):
    return db.builders.get(subdivision["builder_id"]) if subdivision else None


def home_of_rating(rating):
    return db.homes.get(rating["home_id"])


def subdivision_of_rating(rating):
    home = home_of_rating(rating)
    return subdivision_of_home(home) if home else None


def builder_of_rating(rating):
    return builder_of_subdivision(subdivision_of_rating(rating))


def plan_of_rating(rating):
    return db.plan_models.get(rating["plan_model_id"])


def rating_of_inspection(inspection):
    return db.ratings.get(inspection["rating_id"])


def rating_of_qa_review(review):
    return db.ratings.get(review["rating_id"])


def rating_of_corrective_action(action):
    return db.ratings.get(action["rating_id"])


def rating_of_package(package):
    return db.ratings.get(package["rating_id"])


# --- collections ----------------------------------------------------------
def homes_of_subdivision(subdivision_id):
    return ordered(h for h in db.homes.values() if h["subdivision_id"] == subdivision_id)


def plan_models_of_subdivision(subdivision_id):
    return ordered(
        p for p in db.plan_models.values() if p["subdivision_id"] == subdivision_id
    )


def subdivisions_of_builder(builder_id):
    return ordered(s for s in db.subdivisions.values() if s["builder_id"] == builder_id)


def sample_sets_of_subdivision(subdivision_id):
    return ordered(
        s for s in db.sample_sets.values() if s["subdivision_id"] == subdivision_id
    )


def members_of_sample_set(sample_set_id):
    return ordered(h for h in db.homes.values() if h["sample_set_id"] == sample_set_id)


def ratings_of_home(home_id):
    return ordered(r for r in db.ratings.values() if r["home_id"] == home_id)


def live_rating_of_home(home_id):
    live = [r for r in ratings_of_home(home_id) if r["stage"] in LIVE_STAGES]
    return live[-1] if live else None


def inspections_of_rating(rating_id):
    return ordered(i for i in db.inspections.values() if i["rating_id"] == rating_id)


def tests_of_inspection(inspection_id):
    return ordered(
        t for t in db.diagnostic_tests.values() if t["inspection_id"] == inspection_id
    )


def qa_reviews_of_rating(rating_id):
    return ordered(q for q in db.qa_reviews.values() if q["rating_id"] == rating_id)


def corrective_actions_of_rating(rating_id):
    return ordered(
        c for c in db.corrective_actions.values() if c["rating_id"] == rating_id
    )


def packages_of_rating(rating_id):
    return ordered(
        p for p in db.document_packages.values() if p["rating_id"] == rating_id
    )


def ratings_of_builder(builder_id):
    result = []
    for rating in db.ratings.values():
        builder = builder_of_rating(rating)
        if builder is not None and builder["id"] == builder_id:
            result.append(rating)
    return ordered(result)


def packages_of_builder(builder_id):
    result = []
    for package in db.document_packages.values():
        rating = rating_of_package(package)
        if rating is None:
            continue
        builder = builder_of_rating(rating)
        if builder is not None and builder["id"] == builder_id:
            result.append(package)
    return ordered(result)


def corrective_actions_of_builder(builder_id):
    result = []
    for action in db.corrective_actions.values():
        rating = rating_of_corrective_action(action)
        if rating is None:
            continue
        builder = builder_of_rating(rating)
        if builder is not None and builder["id"] == builder_id:
            result.append(action)
    return ordered(result)


def has_unresolved_corrective_action(rating_id):
    return any(
        c["status"] in UNRESOLVED_CA_STATUSES
        for c in corrective_actions_of_rating(rating_id)
    )


def governing_final(rating):
    """The newest FINAL checkpoint that is closed and carries both governing tests.

    Returns (inspection, blower_door_test, duct_leakage_test) or None.
    """
    best = None
    for inspection in inspections_of_rating(rating["id"]):
        if inspection["checkpoint"] != "FINAL":
            continue
        if inspection["status"] not in ("PASSED", "FAILED"):
            continue
        tests = tests_of_inspection(inspection["id"])
        blower = [t for t in tests if t["test_type"] == "BLOWER_DOOR"]
        duct = [t for t in tests if t["test_type"] == "DUCT_LEAKAGE_TOTAL"]
        if not blower or not duct:
            continue
        candidate = (inspection, blower[-1], duct[-1])
        if best is None or inspection["_seq"] > best[0]["_seq"]:
            best = candidate
    return best
