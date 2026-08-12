"""Flask app object, error handlers, and small shared route helpers."""
from flask import Flask

import core
from core import ApiError, fail

app = Flask(__name__)


@app.errorhandler(ApiError)
def handle_api_error(err):
    return core.error_response(err)


@app.errorhandler(404)
def handle_404(err):
    return core.error_response(ApiError("ERR_NOT_FOUND", 404, "Resource not found"))


@app.errorhandler(405)
def handle_405(err):
    return core.error_response(ApiError("ERR_NOT_FOUND", 404, "Resource not found"))


@app.errorhandler(500)
def handle_500(err):
    return core.error_response(ApiError("ERR_INVALID_REQUEST", 400, str(err)))


def fetch(store, entity_id, what="Resource"):
    rec = store.get(entity_id)
    if rec is None:
        fail("ERR_NOT_FOUND", 404, "%s not found: %s" % (what, entity_id))
    return rec


def new_record():
    ts = core.stamp()
    return {"id": core.new_id(), "_seq": core.next_seq(), "version": 1,
            "created_at": ts, "updated_at": ts}
