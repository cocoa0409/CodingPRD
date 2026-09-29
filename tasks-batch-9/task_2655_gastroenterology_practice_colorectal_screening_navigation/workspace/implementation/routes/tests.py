"""Non-invasive stool tests and the positive-result cascade."""
from flask import Blueprint

from core import by_seq, db, fail, now_iso, touch
from core import respond_list, respond_object
from validation import (
    apply_page,
    auth,
    body,
    filter_enum,
    filter_value,
    pagination,
    req_enum,
)
from services import get_episode, get_test, positive_noninvasive_cascade

bp = Blueprint("tests", __name__)

RESULTS = ("PENDING", "NEGATIVE", "POSITIVE", "INSUFFICIENT_SPECIMEN")


@bp.get("/noninvasive-tests/<test_id>")
def read_test(test_id):
    auth("PracticeAdmin", "ReferralCoordinator", "PatientNavigator", "Pathologist")
    return respond_object(get_test(test_id))


@bp.get("/noninvasive-tests")
def list_tests():
    auth("PracticeAdmin", "ReferralCoordinator", "PatientNavigator", "Pathologist")
    limit, offset = pagination()
    episode_id = filter_value("episode_id")
    follow_up_episode_id = filter_value("follow_up_episode_id")
    result = filter_enum("result", RESULTS)
    test_type = filter_enum("test_type", ("FIT", "MT_SDNA"))
    rows = by_seq(list(db.tests.values()))
    if episode_id is not None:
        rows = [r for r in rows if r["episode_id"] == episode_id]
    if follow_up_episode_id is not None:
        rows = [r for r in rows if r["follow_up_episode_id"] == follow_up_episode_id]
    if result is not None:
        rows = [r for r in rows if r["result"] == result]
    if test_type is not None:
        rows = [r for r in rows if r["test_type"] == test_type]
    page, meta = apply_page(rows, limit, offset)
    return respond_list(page, meta)


@bp.post("/noninvasive-tests/<test_id>/result")
def post_result(test_id):
    auth("Pathologist")
    data = body()
    result = req_enum(data, "result", ("NEGATIVE", "POSITIVE", "INSUFFICIENT_SPECIMEN"))

    test = get_test(test_id)
    if test["result"] != "PENDING":
        fail("ERR_TEST_ALREADY_RESULTED",
             "The test has already been resulted as %s." % test["result"])

    test["result"] = result
    test["resulted_at"] = now_iso()
    if result == "POSITIVE":
        ordering_episode = db.episodes.get(test["episode_id"])
        if ordering_episode is not None:
            positive_noninvasive_cascade(test, ordering_episode)
    touch(test)
    return respond_object(test)
